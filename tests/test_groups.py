from tests.conftest import login


def _list(client, headers, title="Súper", kind="shopping"):
    return client.post("/api/lists", json={"title": title, "kind": kind}, headers=headers).json()


def test_group_shares_lists_sections_and_trackers(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    caro = login(client, "caro@correo.com", "Caro")

    family = client.post("/api/groups", json={"name": "Familia"}, headers=ana).json()
    assert family["role"] == "owner" and family["members"] == [] and family["shared"] == []
    added = client.post(f"/api/groups/{family['id']}/members", json={"email": "Beto@correo.com"}, headers=ana).json()
    assert added["status"] == "accepted" and added["name"] == "Beto"

    shopping = _list(client, ana)
    space = next(s for s in client.get("/api/spaces?kind=payments", headers=ana).json() if s["ownerId"])
    nanny = client.post("/api/trackers", json={"name": "Niñera", "icon": "child"}, headers=ana).json()

    # Antes de compartir, Beto no ve nada de Ana.
    assert client.get(f"/api/lists/{shopping['id']}", headers=beto).status_code == 404

    gid = family["id"]
    assert client.put(f"/api/lists/{shopping['id']}/groups/{gid}", json={"role": "editor"}, headers=ana).status_code == 204
    assert client.put(f"/api/spaces/{space['id']}/groups/{gid}", json={"role": "viewer"}, headers=ana).status_code == 204
    assert client.put(f"/api/trackers/{nanny['id']}/groups/{gid}", json={}, headers=ana).status_code == 204

    # Beto ve las tres cosas con el permiso del grupo.
    assert [l["id"] for l in client.get("/api/lists", headers=beto).json()] == [shopping["id"]]
    assert client.post(f"/api/lists/{shopping['id']}/items", json={"text": "Pan"}, headers=beto).status_code == 201
    spaces = {s["id"]: s for s in client.get("/api/spaces", headers=beto).json()}
    assert spaces[space["id"]]["groups"] == [{"groupId": gid, "groupName": "Familia", "role": "viewer"}]
    viewer_reminder = {"kind": "payments", "spaceId": space["id"], "title": "Luz", "nextDue": "2026-11-05"}
    assert client.post("/api/reminders", json=viewer_reminder, headers=beto).status_code == 403
    tracker = next(t for t in client.get("/api/trackers", headers=beto).json() if t["id"] == nanny["id"])
    assert tracker["role"] == "editor" and tracker["groups"][0]["groupName"] == "Familia"

    # La pantalla del grupo lista lo compartido.
    shared = client.get("/api/groups", headers=beto).json()[0]
    assert shared["role"] == "member"
    assert [(i["type"], i["title"]) for i in shared["shared"]] == [
        ("list", "Súper"), ("space", "Pagos"), ("tracker", "Niñera"),
    ]

    # Quien entra después con el código ve todo lo que ya estaba compartido.
    code = client.post(f"/api/groups/{gid}/invites", headers=ana).json()["code"]
    assert client.post("/api/join", json={"code": code}, headers=caro).json()["type"] == "group"
    assert [l["id"] for l in client.get("/api/lists", headers=caro).json()] == [shopping["id"]]

    # Solo el dueño de algo lo comparte; un integrante puede salirse y pierde el acceso.
    assert client.put(f"/api/lists/{shopping['id']}/groups/{gid}", json={}, headers=beto).status_code == 403
    assert client.delete(f"/api/groups/{gid}/members/caro@correo.com", headers=caro).status_code == 204
    assert client.get(f"/api/lists/{shopping['id']}", headers=caro).status_code == 404
    assert client.get("/api/groups", headers=caro).json() == []

    # Dejar de compartir y borrar el grupo.
    assert client.delete(f"/api/lists/{shopping['id']}/groups/{gid}", headers=ana).status_code == 204
    assert client.get("/api/lists", headers=beto).json() == []
    assert client.delete(f"/api/groups/{gid}", headers=beto).status_code == 403
    assert client.delete(f"/api/groups/{gid}", headers=ana).status_code == 204
    assert all(t["id"] != nanny["id"] for t in client.get("/api/trackers", headers=beto).json())


def test_group_member_pending_until_register_and_share_requires_membership(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    family = client.post("/api/groups", json={"name": "Familia"}, headers=ana).json()
    pending = client.post(f"/api/groups/{family['id']}/members", json={"email": "dani@correo.com"}, headers=ana).json()
    assert pending["status"] == "pending"
    shopping = _list(client, ana)
    client.put(f"/api/lists/{shopping['id']}/groups/{family['id']}", json={}, headers=ana)

    dani = login(client, "dani@correo.com", "Dani")
    assert [l["id"] for l in client.get("/api/lists", headers=dani).json()] == [shopping["id"]]

    # Beto no está en el grupo: no puede compartir con él ni verlo.
    own = _list(client, beto, "Mía")
    assert client.put(f"/api/lists/{own['id']}/groups/{family['id']}", json={}, headers=beto).status_code == 404
    assert client.get("/api/groups", headers=beto).json() == []


def test_reminder_time_alert_and_linked_list(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    shopping = _list(client, ana, "Compras del mes")
    reminder = client.post("/api/reminders", json={
        "kind": "other", "title": "Ir al súper", "nextDue": "2026-11-15", "every": 1, "unit": "month",
        "dueTime": "18:30", "alertMinutes": 60, "listId": shopping["id"],
    }, headers=ana).json()
    assert reminder["dueTime"] == "18:30:00" and reminder["alertMinutes"] == 60
    assert reminder["listId"] == shopping["id"]

    # Al marcarlo pasa al mes siguiente y conserva la hora.
    done = client.post(f"/api/reminders/{reminder['id']}/done", json={}, headers=ana).json()
    assert done["nextDue"] == "2026-12-15" and done["dueTime"] == "18:30:00"

    # Sin hora no hay anticipación; null quita la lista.
    patched = client.patch(f"/api/reminders/{reminder['id']}", json={"dueTime": None, "listId": None}, headers=ana).json()
    assert patched["dueTime"] is None and patched["alertMinutes"] is None and patched["listId"] is None

    # No se puede adjuntar una lista ajena.
    other = _list(client, beto, "De Beto")
    bad = client.patch(f"/api/reminders/{reminder['id']}", json={"listId": other["id"]}, headers=ana)
    assert bad.status_code == 404

    # Contador con lista de tareas.
    todo = _list(client, ana, "Tareas de la niñera", "todo")
    nanny = client.post("/api/trackers", json={"name": "Niñera", "listId": todo["id"]}, headers=ana).json()
    assert nanny["listId"] == todo["id"]
    cleared = client.patch(f"/api/trackers/{nanny['id']}", json={"listId": None}, headers=ana).json()
    assert cleared["listId"] is None
    # Si se borra la lista, el recordatorio queda sin lista.
    client.patch(f"/api/reminders/{reminder['id']}", json={"listId": shopping["id"]}, headers=ana)
    client.delete(f"/api/lists/{shopping['id']}", headers=ana)
    again = next(r for r in client.get("/api/reminders", headers=ana).json() if r["id"] == reminder["id"])
    assert again["listId"] is None


def test_role_comes_from_direct_share_or_group(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    shopping = _list(client, ana)
    assert shopping["role"] == "owner"
    client.post(f"/api/lists/{shopping['id']}/members", json={"email": "beto@correo.com", "role": "viewer"}, headers=ana)
    assert client.get(f"/api/lists/{shopping['id']}", headers=beto).json()["role"] == "viewer"

    family = client.post("/api/groups", json={"name": "Familia"}, headers=ana).json()
    client.post(f"/api/groups/{family['id']}/members", json={"email": "beto@correo.com"}, headers=ana)
    client.put(f"/api/lists/{shopping['id']}/groups/{family['id']}", json={"role": "editor"}, headers=ana)
    # Gana el mayor permiso: el del grupo.
    assert [l["role"] for l in client.get("/api/lists", headers=beto).json()] == ["editor"]

    space = client.get("/api/spaces?kind=home", headers=ana).json()[0]
    client.put(f"/api/spaces/{space['id']}/groups/{family['id']}", json={"role": "viewer"}, headers=ana)
    roles = {s["id"]: s["role"] for s in client.get("/api/spaces", headers=beto).json()}
    assert roles[space["id"]] == "viewer"
    assert all(r == "owner" for i, r in roles.items() if i != space["id"])
