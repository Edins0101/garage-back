import pytest

from app.push import _console
from tests.conftest import login


@pytest.fixture(autouse=True)
def clean_outbox():
    _console.sent.clear()


def _register(client, headers, token):
    assert client.post("/api/devices", json={"token": token}, headers=headers).status_code == 204


def test_item_added_notifies_other_members_only(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    zoe = login(client, "zoe@correo.com", "Zoe")
    _register(client, ana, "token-ana-0000")
    _register(client, beto, "token-beto-000")
    _register(client, zoe, "token-zoe-0000")

    lst = client.post("/api/lists", json={"title": "Súper", "kind": "shopping"}, headers=ana).json()
    client.post(f"/api/lists/{lst['id']}/members", json={"email": "beto@correo.com", "role": "editor"}, headers=ana)

    client.post(f"/api/lists/{lst['id']}/items", json={"text": "Leche"}, headers=beto)
    # Avisa a Ana (dueña), no a Beto (quien agregó) ni a Zoe (no es miembro).
    assert [token for token, _ in _console.sent] == ["token-ana-0000"]
    push = _console.sent[0][1]
    assert push.title == "Súper" and push.body == "Beto agregó «Leche»"
    assert push.data == {"type": "item_added", "listId": lst["id"]} and push.tag == f"list-{lst['id']}"

    _console.sent.clear()
    client.post(f"/api/lists/{lst['id']}/items", json={"text": "Pan"}, headers=ana)
    assert [token for token, _ in _console.sent] == ["token-beto-000"]


def test_private_list_sends_nothing(client):
    ana = login(client, "ana@correo.com", "Ana")
    _register(client, ana, "token-ana-0000")
    lst = client.post("/api/lists", json={"title": "Mía", "kind": "todo"}, headers=ana).json()
    client.post(f"/api/lists/{lst['id']}/items", json={"text": "Algo"}, headers=ana)
    assert _console.sent == []


def test_join_notifies_owner(client):
    ana = login(client, "ana@correo.com", "Ana")
    _register(client, ana, "token-ana-0000")
    lst = client.post("/api/lists", json={"title": "Casa", "kind": "todo"}, headers=ana).json()
    code = client.post(f"/api/lists/{lst['id']}/invites", headers=ana).json()["code"]

    beto = login(client, "beto@correo.com", "Beto")
    client.post("/api/invites/join", json={"code": code}, headers=beto)
    assert [(t, p.body) for t, p in _console.sent] == [("token-ana-0000", "Beto se unió a la lista")]


def test_device_moves_to_new_user_and_unregisters(client):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    lst = client.post("/api/lists", json={"title": "Casa", "kind": "todo"}, headers=ana).json()
    client.post(f"/api/lists/{lst['id']}/members", json={"email": "beto@correo.com", "role": "editor"}, headers=ana)

    # El mismo teléfono: primero entra Ana y luego Beto. El token pasa a Beto.
    _register(client, ana, "telefono-compartido")
    _register(client, beto, "telefono-compartido")
    client.post(f"/api/lists/{lst['id']}/items", json={"text": "X"}, headers=beto)
    assert _console.sent == []  # Ana ya no tiene teléfonos registrados

    client.post(f"/api/lists/{lst['id']}/items", json={"text": "Y"}, headers=ana)
    assert [t for t, _ in _console.sent] == ["telefono-compartido"]

    # Al cerrar sesión en ese teléfono deja de recibir.
    assert client.delete("/api/devices/telefono-compartido", headers=beto).status_code == 204
    _console.sent.clear()
    client.post(f"/api/lists/{lst['id']}/items", json={"text": "Z"}, headers=ana)
    assert _console.sent == []
