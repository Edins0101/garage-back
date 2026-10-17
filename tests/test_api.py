from app.email import _console
from tests.conftest import last_code, login, register


def test_requires_login(client):
    response = client.get("/api/lists")
    assert response.status_code == 401
    assert response.json() == {"message": "Inicia sesión para continuar"}


def test_me(client):
    headers = login(client, "Ana@Correo.com", "Ana")
    me = client.get("/api/me", headers=headers).json()
    assert me["email"] == "ana@correo.com"
    assert me["name"] == "Ana"


def test_garage_days_crud_and_range(client):
    headers = login(client, "ana@correo.com")
    assert client.put("/api/garage-days/2026-10-12", json={"note": None}, headers=headers).status_code == 200
    day = client.put("/api/garage-days/2026-10-13", json={"note": " Cambio de aceite "}, headers=headers).json()
    assert day["date"] == "2026-10-13"
    assert day["note"] == "Cambio de aceite"
    assert day["createdAt"].endswith("Z")

    # Idempotente: volver a marcar actualiza la nota, no duplica.
    client.put("/api/garage-days/2026-10-13", json={"note": "Lavado"}, headers=headers)
    days = client.get("/api/garage-days", headers=headers).json()
    assert [d["date"] for d in days] == ["2026-10-12", "2026-10-13"]
    assert days[1]["note"] == "Lavado"

    ranged = client.get("/api/garage-days?from=2026-10-13&to=2026-10-31", headers=headers).json()
    assert [d["date"] for d in ranged] == ["2026-10-13"]

    assert client.delete("/api/garage-days/2026-10-12", headers=headers).status_code == 204
    assert len(client.get("/api/garage-days", headers=headers).json()) == 1

    # Cada usuario tiene su propio calendario.
    other = login(client, "beto@correo.com")
    assert client.get("/api/garage-days", headers=other).json() == []


def test_list_and_items_flow(client):
    headers = login(client, "ana@correo.com")
    created = client.post("/api/lists", json={"title": "Súper", "kind": "shopping"}, headers=headers)
    assert created.status_code == 201
    lst = created.json()
    assert lst["sharedWith"] == [] and lst["items"] == [] and lst["ownerId"]

    item = client.post(f"/api/lists/{lst['id']}/items", json={"text": "Leche", "quantity": "2 l"}, headers=headers).json()
    client.post(f"/api/lists/{lst['id']}/items", json={"text": "Pan"}, headers=headers)

    patched = client.patch(f"/api/lists/{lst['id']}/items/{item['id']}", json={"done": True}, headers=headers).json()
    assert patched["done"] is True and patched["doneBy"] is not None

    cleared = client.post(f"/api/lists/{lst['id']}/items/clear-completed", headers=headers).json()
    assert [i["text"] for i in cleared["items"]] == ["Pan"]

    renamed = client.patch(f"/api/lists/{lst['id']}", json={"title": "Supermercado"}, headers=headers).json()
    assert renamed["title"] == "Supermercado"

    assert client.delete(f"/api/lists/{lst['id']}", headers=headers).status_code == 204
    assert client.get("/api/lists", headers=headers).json() == []


def test_validation_error_format(client):
    headers = login(client, "ana@correo.com")
    response = client.post("/api/lists", json={"title": "", "kind": "otra"}, headers=headers)
    assert response.status_code == 422
    assert "message" in response.json()


def test_sharing_by_email_permissions(client):
    owner = login(client, "ana@correo.com", "Ana")
    lst = client.post("/api/lists", json={"title": "Casa", "kind": "todo"}, headers=owner).json()

    # Invitación a alguien que aún no tiene cuenta: queda pendiente.
    member = client.post(
        f"/api/lists/{lst['id']}/members", json={"email": "beto@correo.com", "role": "viewer"}, headers=owner
    ).json()
    assert member["status"] == "pending"

    # Al iniciar sesión, la invitación se acepta sola y ve la lista.
    viewer = login(client, "beto@correo.com", "Beto")
    lists = client.get("/api/lists", headers=viewer).json()
    assert [l["title"] for l in lists] == ["Casa"]
    assert lists[0]["sharedWith"][0]["status"] == "accepted"

    # Un viewer no puede editar ni invitar.
    response = client.post(f"/api/lists/{lst['id']}/items", json={"text": "X"}, headers=viewer)
    assert response.status_code == 403
    response = client.post(
        f"/api/lists/{lst['id']}/members", json={"email": "c@correo.com", "role": "editor"}, headers=viewer
    )
    assert response.status_code == 403

    # Con rol editor sí puede agregar elementos, pero no borrar la lista.
    client.post(f"/api/lists/{lst['id']}/members", json={"email": "beto@correo.com", "role": "editor"}, headers=owner)
    assert client.post(f"/api/lists/{lst['id']}/items", json={"text": "X"}, headers=viewer).status_code == 201
    assert client.delete(f"/api/lists/{lst['id']}", headers=viewer).status_code == 403

    # Un extraño ni siquiera sabe que la lista existe.
    stranger = login(client, "zoe@correo.com")
    assert client.get(f"/api/lists/{lst['id']}", headers=stranger).status_code == 404


def test_invite_code_join(client):
    owner = login(client, "ana@correo.com", "Ana")
    lst = client.post("/api/lists", json={"title": "Súper", "kind": "shopping"}, headers=owner).json()

    invite = client.post(f"/api/lists/{lst['id']}/invites", headers=owner).json()
    assert len(invite["code"]) == 6 and invite["url"].endswith(invite["code"])
    # Reutiliza el código vigente.
    assert client.post(f"/api/lists/{lst['id']}/invites", headers=owner).json()["code"] == invite["code"]

    guest = login(client, "beto@correo.com", "Beto")
    joined = client.post("/api/invites/join", json={"code": invite["code"].lower()}, headers=guest).json()
    assert joined["id"] == lst["id"]
    assert [m["email"] for m in joined["sharedWith"]] == ["beto@correo.com"]

    # Unirse dos veces no duplica al miembro.
    again = client.post("/api/invites/join", json={"code": invite["code"]}, headers=guest).json()
    assert len(again["sharedWith"]) == 1

    assert client.post("/api/invites/join", json={"code": "ZZZZZZ"}, headers=guest).status_code == 404

    # Un miembro puede salirse de la lista.
    assert client.delete(f"/api/lists/{lst['id']}/members/beto@correo.com", headers=guest).status_code == 204
    assert client.get("/api/lists", headers=guest).json() == []


def test_register_and_login(client):
    created = register(client, "Ana@Correo.com", "Ana")
    assert created.status_code == 201, created.text
    assert created.json()["user"]["email"] == "ana@correo.com"

    # El token sirve de inmediato.
    headers = {"Authorization": f"Bearer {created.json()['token']}"}
    assert client.get("/api/me", headers=headers).json()["name"] == "Ana"

    # No se puede registrar dos veces el mismo correo.
    again = client.post("/api/auth/codes", json={"email": "ana@correo.com", "purpose": "register"})
    assert again.status_code == 409

    ok = client.post("/api/auth/login", json={"email": "ANA@correo.com", "password": "secreta123"})
    assert ok.status_code == 200 and ok.json()["token"]

    bad = client.post("/api/auth/login", json={"email": "ana@correo.com", "password": "incorrecta"})
    assert bad.status_code == 401
    assert bad.json() == {"message": "Correo o contraseña incorrectos"}

    unknown = client.post("/api/auth/login", json={"email": "nadie@correo.com", "password": "secreta123"})
    assert unknown.status_code == 401


def test_register_validation(client):
    short = client.post("/api/auth/register", json={"name": "Ana", "email": "ana@correo.com", "password": "123"})
    assert short.status_code == 422
    bad_email = client.post("/api/auth/register", json={"name": "Ana", "email": "no-es-correo", "password": "secreta123"})
    assert bad_email.status_code == 422


def test_register_accepts_pending_invites(client):
    owner = login(client, "ana@correo.com", "Ana")
    lst = client.post("/api/lists", json={"title": "Casa", "kind": "todo"}, headers=owner).json()
    client.post(f"/api/lists/{lst['id']}/members", json={"email": "beto@correo.com", "role": "editor"}, headers=owner)

    token = register(client, "beto@correo.com", "Beto").json()["token"]
    lists = client.get("/api/lists", headers={"Authorization": f"Bearer {token}"}).json()
    assert [l["title"] for l in lists] == ["Casa"]


def test_validation_messages_in_spanish(client):
    short = client.post("/api/auth/register", json={"name": "Ana", "email": "ana@correo.com", "password": "123"})
    assert short.json() == {"message": "La contraseña debe tener al menos 8 caracteres"}
    bad = client.post("/api/auth/register", json={"name": "Ana", "email": "no-es-correo", "password": "secreta123"})
    assert bad.json() == {"message": "El correo no es válido"}


def test_register_requires_valid_code(client):
    body = {"name": "Ana", "email": "ana@correo.com", "password": "secreta123"}
    assert client.post("/api/auth/register", json=body).json() == {"message": "Falta el código que enviamos a tu correo"}

    client.post("/api/auth/codes", json={"email": "ana@correo.com", "purpose": "register"})
    code = last_code("ana@correo.com")
    assert len(code) == 6 and code.isdigit()

    wrong = client.post("/api/auth/register", json={**body, "code": "000000" if code != "000000" else "111111"})
    assert wrong.status_code == 400
    assert "Te quedan 4 intentos" in wrong.json()["message"]

    ok = client.post("/api/auth/register", json={**body, "code": code})
    assert ok.status_code == 201
    # Un código no sirve dos veces.
    assert client.post("/api/auth/codes", json={"email": "ana@correo.com", "purpose": "register"}).status_code == 409


def test_code_attempts_and_resend_limits(client):
    client.post("/api/auth/codes", json={"email": "ana@correo.com", "purpose": "register"})
    code = last_code("ana@correo.com")
    bad = "000000" if code != "000000" else "111111"
    body = {"name": "Ana", "email": "ana@correo.com", "password": "secreta123", "code": bad}
    for _ in range(5):
        client.post("/api/auth/register", json=body)
    # Tras 5 fallos, ni el código correcto sirve.
    blocked = client.post("/api/auth/register", json={**body, "code": code})
    assert blocked.json()["message"] == "Demasiados intentos. Pide un código nuevo."

    # No se puede pedir otro código antes de 60 segundos.
    resend = client.post("/api/auth/codes", json={"email": "ana@correo.com", "purpose": "register"})
    assert resend.status_code == 429


def test_password_reset(client):
    register(client, "ana@correo.com", "Ana", password="vieja12345")

    # Para un correo sin cuenta, la respuesta es igual pero no se envía nada.
    sent_before = len(_console.outbox)
    unknown = client.post("/api/auth/codes", json={"email": "nadie@correo.com", "purpose": "reset"})
    assert unknown.status_code == 202
    assert len(_console.outbox) == sent_before

    assert client.post("/api/auth/codes", json={"email": "ana@correo.com", "purpose": "reset"}).status_code == 202
    code = last_code("ana@correo.com")
    reset = client.post(
        "/api/auth/password/reset", json={"email": "ana@correo.com", "code": code, "password": "nueva12345"}
    )
    assert reset.status_code == 200 and reset.json()["token"]

    assert client.post("/api/auth/login", json={"email": "ana@correo.com", "password": "vieja12345"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ana@correo.com", "password": "nueva12345"}).status_code == 200



def test_items_with_sections(client):
    h = login(client, "ana@correo.com")
    lst = client.post("/api/lists", json={"title": "Casa", "kind": "shopping"}, headers=h).json()
    soap = client.post(f"/api/lists/{lst['id']}/items", json={"text": "Jabón", "section": " Baño "}, headers=h).json()
    bread = client.post(f"/api/lists/{lst['id']}/items", json={"text": "Pan"}, headers=h).json()
    assert soap["section"] == "Baño" and bread["section"] is None
    moved = client.patch(f"/api/lists/{lst['id']}/items/{bread['id']}", json={"section": "Cocina"}, headers=h).json()
    assert moved["section"] == "Cocina"
    # Cambiar otra cosa no la saca de su sección; null sí.
    assert client.patch(f"/api/lists/{lst['id']}/items/{bread['id']}", json={"done": True}, headers=h).json()["section"] == "Cocina"
    cleared = client.patch(f"/api/lists/{lst['id']}/items/{bread['id']}", json={"section": None}, headers=h).json()
    assert cleared["section"] is None


def test_join_page_and_assetlinks(client):
    page = client.get("/join/ab12cd")
    assert page.status_code == 200
    assert "AB12CD" in page.text and "intent://join/AB12CD" in page.text
    assert client.get("/join/<script>").status_code == 404

    links = client.get("/.well-known/assetlinks.json").json()
    assert links[0]["target"]["package_name"] == "com.arianna.app"
    assert len(links[0]["target"]["sha256_cert_fingerprints"][0]) == 95
