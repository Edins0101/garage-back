import datetime as dt

import pytest

from app.db import get_db
from app.main import app
from app.models import Appliance, utcnow
from app.push import _console
from tests.conftest import login


@pytest.fixture(autouse=True)
def clean_outbox():
    _console.sent.clear()


def _register(client, headers, token):
    assert client.post("/api/devices", json={"token": token}, headers=headers).status_code == 204


def _sent_to(token):
    return [push.body for t, push in _console.sent if t == token]


def _family(client):
    """Ana crea la lavadora y la comparte con su grupo, donde están Beto (editor) y Caro."""
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    caro = login(client, "caro@correo.com", "Caro")
    for headers, token in ((ana, "token-ana-0000"), (beto, "token-beto-000"), (caro, "token-caro-000")):
        _register(client, headers, token)
    group = client.post("/api/groups", json={"name": "Casa"}, headers=ana).json()
    for email in ("beto@correo.com", "caro@correo.com"):
        client.post(f"/api/groups/{group['id']}/members", json={"email": email}, headers=ana)
    washer = client.post("/api/appliances", json={"name": "Lavadora", "defaultMinutes": 45}, headers=ana).json()
    put = client.put(f"/api/appliances/{washer['id']}/groups/{group['id']}", json={"role": "editor"}, headers=ana)
    assert put.status_code == 204
    return ana, beto, caro, washer, group


def test_busy_and_free_notify_the_others(client):
    ana, beto, caro, washer, group = _family(client)
    assert washer["busy"] is False and washer["role"] == "owner" and washer["defaultMinutes"] == 45

    # Beto la ocupa: se estima con los 45 min por defecto y se avisa a Ana y a Caro (no a él).
    busy = client.post(f"/api/appliances/{washer['id']}/start", json={}, headers=beto).json()
    assert busy["busy"] is True and busy["busyByName"] == "Beto" and busy["role"] == "editor"
    end = dt.datetime.fromisoformat(busy["expectedEnd"].replace("Z", "+00:00"))
    assert dt.timedelta(minutes=44) < end - utcnow() <= dt.timedelta(minutes=45)
    assert _sent_to("token-ana-0000")[0].startswith("Beto empezó a usar Lavadora · libre aprox. a las ")
    assert _sent_to("token-beto-000") == []

    # Ana la ve ocupada y no puede ocuparla; Caro elige que solo le avisen cuando se libere.
    assert client.get("/api/appliances", headers=ana).json()[0]["busyByName"] == "Beto"
    conflict = client.post(f"/api/appliances/{washer['id']}/start", json={}, headers=ana)
    assert conflict.status_code == 409 and conflict.json()["message"] == "Beto lo está usando"
    assert client.put(f"/api/appliances/{washer['id']}/notify", json={"mode": "free"}, headers=caro).json()["notify"] == "free"

    # Ana la libera por Beto (se olvidó): avisa a Beto y a Caro.
    _console.sent.clear()
    free = client.post(f"/api/appliances/{washer['id']}/finish", headers=ana).json()
    assert free["busy"] is False and free["busyByName"] is None
    assert _sent_to("token-beto-000") == ["Ana liberó Lavadora (lo usaba Beto): ya está libre"]
    assert _sent_to("token-caro-000") == ["Ana liberó Lavadora (lo usaba Beto): ya está libre"]

    # Caro no recibe el aviso de "empezó a usar".
    _console.sent.clear()
    client.post(f"/api/appliances/{washer['id']}/start", json={"minutes": 10}, headers=ana)
    assert _sent_to("token-caro-000") == [] and len(_sent_to("token-beto-000")) == 1

    history = client.get(f"/api/appliances/{washer['id']}/history", headers=caro).json()
    assert [(u["userName"], u["endedByName"]) for u in history] == [("Ana", None), ("Beto", "Ana")]

    # En la pantalla del grupo va aparte (la app v0.8 no conoce el tipo "appliance").
    shown = client.get("/api/groups", headers=beto).json()[0]
    assert shown["shared"] == [] and [i["title"] for i in shown["sharedAppliances"]] == ["Lavadora"]


def test_released_automatically_after_expected_end(client):
    ana, beto, caro, washer, group = _family(client)
    client.post(f"/api/appliances/{washer['id']}/start", json={"minutes": 30}, headers=beto)

    # Pasó la hora estimada + el margen y nadie la liberó.
    db = next(app.dependency_overrides[get_db]())
    appliance = db.get(Appliance, washer["id"])
    appliance.busy_since = utcnow() - dt.timedelta(hours=2)
    appliance.expected_end = utcnow() - dt.timedelta(hours=1)
    db.commit()
    db.close()
    _console.sent.clear()
    listed = client.get("/api/appliances", headers=caro).json()[0]
    assert listed["busy"] is False
    assert "se liberó solo" in _sent_to("token-ana-0000")[0]
    assert client.get(f"/api/appliances/{washer['id']}/history", headers=ana).json()[0]["auto"] is True


def test_permissions(client):
    ana, beto, caro, washer, group = _family(client)
    zoe = login(client, "zoe@correo.com", "Zoe")
    assert client.get(f"/api/appliances/{washer['id']}", headers=zoe).status_code == 404
    assert client.get("/api/appliances", headers=zoe).json() == []

    # Con "solo ver" se ve el estado pero no se usa; solo la dueña edita o borra.
    client.put(f"/api/appliances/{washer['id']}/groups/{group['id']}", json={"role": "viewer"}, headers=ana)
    assert client.post(f"/api/appliances/{washer['id']}/start", json={}, headers=beto).status_code == 403
    assert client.patch(f"/api/appliances/{washer['id']}", json={"name": "X"}, headers=beto).status_code == 403
    patched = client.patch(f"/api/appliances/{washer['id']}", json={"defaultMinutes": None, "icon": "dryer"}, headers=ana)
    assert patched.json()["defaultMinutes"] is None and patched.json()["icon"] == "dryer"
    assert client.delete(f"/api/appliances/{washer['id']}", headers=ana).status_code == 204
    assert client.get("/api/appliances", headers=beto).json() == []
