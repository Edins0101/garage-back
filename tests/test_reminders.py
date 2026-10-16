import datetime as dt

import pytest

from app.push import _console
from app.reminders import add_months, advance
from tests.conftest import login


@pytest.fixture(autouse=True)
def clean_outbox():
    _console.sent.clear()


def _new(client, headers, **fields):
    body = {"kind": "payments", "title": "Luz", "amount": "32.50", "every": 1, "unit": "month",
            "nextDue": "2026-01-31", **fields}
    response = client.post("/api/reminders", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_months_keep_the_original_day():
    assert add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    assert add_months(dt.date(2026, 2, 28), 1, anchor_day=31) == dt.date(2026, 3, 31)
    assert add_months(dt.date(2026, 11, 15), 3) == dt.date(2027, 2, 15)
    assert advance(dt.date(2024, 2, 29), 1, "year", 29) == dt.date(2025, 2, 28)
    assert advance(dt.date(2026, 10, 16), 2, "week", None) == dt.date(2026, 10, 30)


def test_create_list_and_mark_paid(client):
    ana = login(client, "ana@correo.com", "Ana")
    luz = _new(client, ana)
    assert luz["kind"] == "payments" and luz["amount"] == 32.5 and luz["lastDone"] is None

    paid = client.post(f"/api/reminders/{luz['id']}/done", json={"amount": "35.10"}, headers=ana).json()
    assert paid["nextDue"] == "2026-02-28"
    assert paid["lastDone"]["amount"] == 35.1 and paid["lastDone"]["dueDate"] == "2026-01-31"
    assert paid["lastDone"]["doneByName"] == "Ana"

    # Sin monto, el historial guarda el estimado; y en marzo vuelve al día 31.
    again = client.post(f"/api/reminders/{luz['id']}/done", json={}, headers=ana).json()
    assert again["nextDue"] == "2026-03-31" and again["lastDone"]["amount"] == 32.5

    history = client.get(f"/api/reminders/{luz['id']}/history", headers=ana).json()
    assert [h["dueDate"] for h in history] == ["2026-02-28", "2026-01-31"]

    undone = client.post(f"/api/reminders/{luz['id']}/undo", headers=ana).json()
    assert undone["nextDue"] == "2026-02-28" and undone["lastDone"]["dueDate"] == "2026-01-31"

    listed = client.get("/api/reminders", params={"kind": "payments"}, headers=ana).json()
    assert [r["id"] for r in listed] == [luz["id"]]
    assert client.get("/api/reminders", params={"kind": "home"}, headers=ana).json() == []


def test_one_time_reminder_finishes(client):
    ana = login(client, "ana@correo.com", "Ana")
    soat = _new(client, ana, title="SOAT", every=None, unit=None, nextDue="2026-12-01")
    done = client.post(f"/api/reminders/{soat['id']}/done", json={}, headers=ana).json()
    assert done["finished"] is True and done["nextDue"] == "2026-12-01"
    assert client.post(f"/api/reminders/{soat['id']}/done", json={}, headers=ana).status_code == 409
    assert client.post(f"/api/reminders/{soat['id']}/undo", headers=ana).json()["finished"] is False


def test_repeat_needs_number_and_unit(client):
    ana = login(client, "ana@correo.com", "Ana")
    body = {"kind": "payments", "title": "Luz", "every": 1, "nextDue": "2026-01-31"}
    assert client.post("/api/reminders", json=body, headers=ana).status_code == 422
    luz = _new(client, ana)
    assert client.patch(f"/api/reminders/{luz['id']}", json={"unit": None}, headers=ana).status_code == 422
    once = client.patch(f"/api/reminders/{luz['id']}", json={"every": None, "unit": None, "amount": None}, headers=ana)
    assert once.json()["every"] is None and once.json()["amount"] is None


def test_shared_section_and_permissions(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    zoe = login(client, "zoe@correo.com", "Zoe")
    for headers, token in ((ana, "token-ana-0000"), (beto, "token-beto-000")):
        client.post("/api/devices", json={"token": token}, headers=headers)
    luz = _new(client, ana)

    # Zoe no ve los pagos de Ana ni puede tocarlos.
    assert client.get("/api/reminders", params={"kind": "payments"}, headers=zoe).json() == []
    assert client.post(f"/api/reminders/{luz['id']}/done", json={}, headers=zoe).status_code == 404

    space = client.get("/api/spaces", params={"kind": "payments"}, headers=ana).json()[0]
    assert space["ownerName"] == "Ana" and space["members"] == []
    client.post(f"/api/spaces/{space['id']}/members", json={"email": "beto@correo.com", "role": "editor"}, headers=ana)

    # Beto ve su sección (vacía) y la de Ana.
    spaces = client.get("/api/spaces", params={"kind": "payments"}, headers=beto).json()
    assert [s["ownerName"] for s in spaces] == ["Beto", "Ana"]
    assert [r["title"] for r in client.get("/api/reminders", params={"kind": "payments"}, headers=beto).json()] == ["Luz"]

    # Beto marca la luz como pagada: le avisa a Ana.
    client.post(f"/api/reminders/{luz['id']}/done", json={}, headers=beto)
    assert [token for token, _ in _console.sent] == ["token-ana-0000"]
    assert _console.sent[0][1].body == "Beto marcó «Luz» como pagado"

    # Beto agrega un pago en la sección de Ana: le avisa a Ana.
    _console.sent.clear()
    _new(client, beto, title="Internet", spaceId=space["id"])
    assert _console.sent[0][1].body == "Beto agregó «Internet»"

    # Solo la dueña comparte; Beto puede salirse.
    assert client.post(f"/api/spaces/{space['id']}/invites", headers=beto).status_code == 403
    assert client.delete(f"/api/spaces/{space['id']}/members/beto@correo.com", headers=beto).status_code == 204
    assert client.get("/api/reminders", params={"kind": "payments"}, headers=beto).json() == []


def test_viewer_cannot_mark(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    luz = _new(client, ana)
    space = client.get("/api/spaces", params={"kind": "payments"}, headers=ana).json()[0]
    client.post(f"/api/spaces/{space['id']}/members", json={"email": "beto@correo.com", "role": "viewer"}, headers=ana)
    assert client.post(f"/api/reminders/{luz['id']}/done", json={}, headers=beto).status_code == 403


def test_join_section_with_code(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    _new(client, ana)
    space = client.get("/api/spaces", params={"kind": "payments"}, headers=ana).json()[0]
    invite = client.post(f"/api/spaces/{space['id']}/invites", headers=ana).json()
    assert invite["spaceId"] == space["id"] and invite["listId"] is None
    assert invite["url"].endswith("/" + invite["code"])

    # El endpoint viejo de listas no acepta códigos de sección.
    assert client.post("/api/invites/join", json={"code": invite["code"]}, headers=beto).status_code == 404
    joined = client.post("/api/join", json={"code": invite["code"].lower()}, headers=beto).json()
    assert joined == {"type": "space", "listId": None, "spaceId": space["id"], "kind": "payments"}
    assert len(client.get("/api/reminders", params={"kind": "payments"}, headers=beto).json()) == 1

    # Y POST /join también sirve para listas.
    lst = client.post("/api/lists", json={"title": "Súper", "kind": "shopping"}, headers=ana).json()
    code = client.post(f"/api/lists/{lst['id']}/invites", headers=ana).json()["code"]
    assert client.post("/api/join", json={"code": code}, headers=beto).json()["listId"] == lst["id"]


def test_pending_space_invite_is_linked_on_login(client):
    ana = login(client, "ana@correo.com", "Ana")
    _new(client, ana)
    space = client.get("/api/spaces", params={"kind": "payments"}, headers=ana).json()[0]
    member = client.post(f"/api/spaces/{space['id']}/members", json={"email": "nuevo@correo.com", "role": "editor"}, headers=ana)
    assert member.json()["status"] == "pending"
    nuevo = login(client, "nuevo@correo.com", "Nuevo")
    assert len(client.get("/api/reminders", params={"kind": "payments"}, headers=nuevo).json()) == 1
