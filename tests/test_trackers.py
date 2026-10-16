import datetime as dt

import pytest

from tests.conftest import login


@pytest.fixture
def clock(monkeypatch):
    state = {"today": dt.date(2026, 10, 14)}

    def fake_today():
        return state["today"]

    monkeypatch.setattr("app.garage.today", fake_today)
    monkeypatch.setattr("app.routers.garage.today", fake_today)
    return state


def test_several_trackers_keep_separate_accounts(client, clock):
    ana = login(client, "ana@correo.com", "Ana")
    assert client.get("/api/trackers", headers=ana).json() == []

    nanny = client.post(
        "/api/trackers", json={"name": "Niñera", "icon": "child", "dailyRate": "25"}, headers=ana
    ).json()
    work = client.post(
        "/api/trackers", json={"name": "Días trabajados", "icon": "work", "direction": "earn", "dailyRate": "80"},
        headers=ana,
    ).json()
    assert nanny["direction"] == "pay" and work["direction"] == "earn" and nanny["summary"]["pending"] == 0

    for day in ("2026-10-12", "2026-10-13"):
        client.put(f"/api/trackers/{nanny['id']}/days/{day}", json={}, headers=ana)
    client.put(f"/api/trackers/{work['id']}/days/2026-10-13", json={"note": "Cliente A"}, headers=ana)
    client.post(f"/api/trackers/{nanny['id']}/days/2026-10-13/charges", json={"description": "Taxi", "amount": "4"}, headers=ana)
    client.post(f"/api/trackers/{nanny['id']}/payments", json={"date": "2026-10-13", "amount": "30"}, headers=ana)

    listed = {t["name"]: t["summary"] for t in client.get("/api/trackers", headers=ana).json()}
    assert listed["Niñera"]["days"] == 2 and listed["Niñera"]["pending"] == 24.0  # 50 + 4 - 30
    assert listed["Días trabajados"]["total"] == 80.0
    assert len(client.get(f"/api/trackers/{work['id']}/days", headers=ana).json()) == 1

    # Mismo día en dos contadores: no chocan.
    client.put(f"/api/trackers/{work['id']}/days/2026-10-12", json={}, headers=ana)
    assert client.get(f"/api/trackers/{nanny['id']}/summary", headers=ana).json()["days"] == 2

    # Cambiar tarifa y marcado automático por contador.
    patched = client.patch(f"/api/trackers/{work['id']}", json={"name": "Freelance", "autoMark": True}, headers=ana).json()
    assert patched["name"] == "Freelance" and patched["autoMark"] is True
    clock["today"] = dt.date(2026, 10, 16)
    assert client.get(f"/api/trackers/{work['id']}/summary", headers=ana).json()["days"] == 5  # 12, 13, 14, 15, 16

    # Borrar un contador borra sus días y pagos.
    assert client.delete(f"/api/trackers/{nanny['id']}", headers=ana).status_code == 204
    assert [t["name"] for t in client.get("/api/trackers", headers=ana).json()] == ["Freelance"]


def test_trackers_are_private(client, clock):
    ana = login(client, "ana@correo.com", "Ana")
    beto = login(client, "beto@correo.com", "Beto")
    tracker = client.post("/api/trackers", json={"name": "Expreso"}, headers=ana).json()
    assert client.get(f"/api/trackers/{tracker['id']}/days", headers=beto).status_code == 404
    assert client.put(f"/api/trackers/{tracker['id']}/days/2026-10-14", json={}, headers=beto).status_code == 404
    assert client.get("/api/trackers", headers=beto).json() == []


def test_old_garage_routes_use_the_first_tracker(client, clock):
    ana = login(client, "ana@correo.com", "Ana")
    client.put("/api/garage/settings", json={"dailyRate": "5"}, headers=ana)
    client.put("/api/garage-days/2026-10-13", json={}, headers=ana)
    client.post("/api/payments", json={"date": "2026-10-13", "amount": "2"}, headers=ana)

    trackers = client.get("/api/trackers", headers=ana).json()
    assert [(t["name"], t["dailyRate"], t["summary"]["pending"]) for t in trackers] == [("Mi garaje", 5.0, 3.0)]
    garage = trackers[0]["id"]
    assert len(client.get(f"/api/trackers/{garage}/days", headers=ana).json()) == 1
    payment = client.get(f"/api/trackers/{garage}/payments", headers=ana).json()[0]
    assert client.delete(f"/api/payments/{payment['id']}", headers=ana).status_code == 204


def test_share_tracker_with_roles(client, clock):
    from app.push import _console

    _console.sent.clear()
    ana = login(client, "ana@correo.com", "Ana")
    pareja = login(client, "pareja@correo.com", "Pareja")
    ninera = login(client, "ninera@correo.com", "Rosa")
    client.post("/api/devices", json={"token": "token-ana-0000"}, headers=ana)
    client.post("/api/devices", json={"token": "token-rosa-000"}, headers=ninera)
    tracker = client.post("/api/trackers", json={"name": "Niñera", "icon": "child", "dailyRate": "25"}, headers=ana).json()
    tid = tracker["id"]
    assert tracker["role"] == "owner" and tracker["ownerName"] == "Ana"

    # Pareja por correo con edición; la niñera con código (entra como "solo ver").
    member = client.post(f"/api/trackers/{tid}/members", json={"email": "pareja@correo.com", "role": "editor"}, headers=ana)
    assert member.json()["status"] == "accepted"
    code = client.post(f"/api/trackers/{tid}/invites", headers=ana).json()
    assert code["trackerId"] == tid
    joined = client.post("/api/join", json={"code": code["code"]}, headers=ninera).json()
    assert joined["type"] == "tracker" and joined["trackerId"] == tid

    seen = client.get("/api/trackers", headers=ninera).json()
    assert [(t["name"], t["role"], t["ownerName"]) for t in seen] == [("Niñera", "viewer", "Ana")]
    assert {m["email"]: m["role"] for m in seen[0]["members"]} == {"pareja@correo.com": "editor", "ninera@correo.com": "viewer"}

    # La pareja marca días y paga; la niñera solo ve.
    assert client.put(f"/api/trackers/{tid}/days/2026-10-13", json={}, headers=pareja).status_code == 200
    assert client.put(f"/api/trackers/{tid}/days/2026-10-14", json={}, headers=ninera).status_code == 403
    assert client.get(f"/api/trackers/{tid}/days", headers=ninera).status_code == 200
    client.post(f"/api/trackers/{tid}/payments", json={"date": "2026-10-14", "amount": "25"}, headers=pareja)
    assert sorted(t for t, _ in _console.sent) == ["token-ana-0000", "token-rosa-000"]
    assert _console.sent[0][1].body == "Pareja registró un pago de $25.00"

    # Solo la dueña configura y comparte; un miembro puede salirse.
    assert client.patch(f"/api/trackers/{tid}", json={"dailyRate": "30"}, headers=pareja).status_code == 403
    assert client.post(f"/api/trackers/{tid}/invites", headers=pareja).status_code == 403
    assert client.delete(f"/api/trackers/{tid}/members/ninera@correo.com", headers=ninera).status_code == 204
    assert client.get("/api/trackers", headers=ninera).json() == []
    # Las rutas viejas de la pareja no tocan el contador de Ana.
    assert client.get("/api/garage-days", headers=pareja).json() == []
