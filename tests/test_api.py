from tests.conftest import login


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
