import datetime as dt

import pytest

from tests.conftest import login


@pytest.fixture
def clock(monkeypatch):
    """Permite fijar el "hoy" de la app en los tests."""
    state = {"today": dt.date(2026, 10, 14)}

    def fake_today():
        return state["today"]

    monkeypatch.setattr("app.garage.today", fake_today)
    monkeypatch.setattr("app.routers.garage.today", fake_today)
    return state


def test_rate_is_snapshotted_per_day(client, clock):
    h = login(client, "ana@correo.com")
    # Día marcado sin tarifa configurada.
    assert client.put("/api/garage-days/2026-10-10", json={}, headers=h).json()["rate"] is None

    # Al configurar la tarifa se aplica a los días sin tarifa.
    settings = client.put("/api/garage/settings", json={"dailyRate": "5.00"}, headers=h).json()
    assert settings["dailyRate"] == 5.0 and settings["today"] == "2026-10-14"
    assert client.get("/api/garage-days", headers=h).json()[0]["rate"] == 5.0

    client.put("/api/garage-days/2026-10-11", json={}, headers=h)
    # Cambiar la tarifa no altera los días que ya tenían.
    client.put("/api/garage/settings", json={"dailyRate": 6}, headers=h)
    client.put("/api/garage-days/2026-10-12", json={"note": "x"}, headers=h)
    rates = [d["rate"] for d in client.get("/api/garage-days", headers=h).json()]
    assert rates == [5.0, 5.0, 6.0]

    # Se puede ajustar la tarifa de un día puntual sin tocar la nota.
    day = client.put("/api/garage-days/2026-10-12", json={"rate": "4.50"}, headers=h).json()
    assert day["rate"] == 4.5 and day["note"] == "x"


def test_charges_and_summary_with_payments(client, clock):
    h = login(client, "ana@correo.com")
    client.put("/api/garage/settings", json={"dailyRate": 5}, headers=h)
    for d in ("2026-10-12", "2026-10-13", "2026-10-14", "2026-10-20"):  # el 20 es futuro
        client.put(f"/api/garage-days/{d}", json={}, headers=h)

    wash = client.post("/api/garage-days/2026-10-13/charges", json={"description": "Lavado", "amount": 3}, headers=h)
    assert wash.status_code == 201
    client.post("/api/garage-days/2026-10-13/charges", json={"description": "Llaves", "amount": "1.50"}, headers=h)
    day = next(d for d in client.get("/api/garage-days", headers=h).json() if d["date"] == "2026-10-13")
    assert [c["description"] for c in day["charges"]] == ["Lavado", "Llaves"]
    assert day["total"] == 9.5

    client.post("/api/payments", json={"date": "2026-10-13", "amount": 10, "note": "Efectivo"}, headers=h)
    s = client.get("/api/garage/summary", headers=h).json()
    assert s == {
        "until": "2026-10-14",
        "dailyRate": 5.0,
        "days": 3,
        "daysWithoutRate": 0,
        "daysTotal": 15.0,
        "chargesTotal": 4.5,
        "total": 19.5,
        "paid": 10.0,
        "pending": 9.5,
    }

    # Quitar un cargo y un pago.
    assert client.delete(f"/api/garage-charges/{wash.json()['id']}", headers=h).status_code == 204
    payment_id = client.get("/api/payments", headers=h).json()[0]["id"]
    assert client.delete(f"/api/payments/{payment_id}", headers=h).status_code == 204
    s = client.get("/api/garage/summary", headers=h).json()
    assert s["total"] == 16.5 and s["paid"] == 0 and s["pending"] == 16.5

    # Borrar el día borra sus cargos.
    client.delete("/api/garage-days/2026-10-13", headers=h)
    assert client.get("/api/garage/summary", headers=h).json()["chargesTotal"] == 0


def test_charge_on_unmarked_day_marks_it(client, clock):
    h = login(client, "ana@correo.com")
    client.put("/api/garage/settings", json={"dailyRate": 5}, headers=h)
    client.post("/api/garage-days/2026-10-01/charges", json={"description": "Multa", "amount": 20}, headers=h)
    days = client.get("/api/garage-days", headers=h).json()
    assert days[0]["date"] == "2026-10-01" and days[0]["total"] == 25.0


def test_money_validation(client, clock):
    h = login(client, "ana@correo.com")
    assert client.put("/api/garage/settings", json={"dailyRate": -1}, headers=h).status_code == 422
    assert client.put("/api/garage/settings", json={"dailyRate": "1.234"}, headers=h).status_code == 422
    assert client.post("/api/payments", json={"date": "2026-10-14", "amount": 0}, headers=h).status_code == 422


def test_data_is_private(client, clock):
    a = login(client, "ana@correo.com")
    b = login(client, "beto@correo.com")
    charge = client.post("/api/garage-days/2026-10-14/charges", json={"description": "X", "amount": 1}, headers=a).json()
    payment = client.post("/api/payments", json={"date": "2026-10-14", "amount": 1}, headers=a).json()
    assert client.delete(f"/api/garage-charges/{charge['id']}", headers=b).status_code == 404
    assert client.delete(f"/api/payments/{payment['id']}", headers=b).status_code == 404
    assert client.get("/api/payments", headers=b).json() == []


def test_auto_mark_fills_missing_days(client, clock):
    h = login(client, "ana@correo.com")
    client.put("/api/garage/settings", json={"dailyRate": 5, "autoMark": True}, headers=h)
    # Al activarlo se marca hoy (no el pasado).
    assert [d["date"] for d in client.get("/api/garage-days", headers=h).json()] == ["2026-10-14"]

    # Pasan 3 días sin abrir la app: se rellenan al consultar.
    clock["today"] = dt.date(2026, 10, 17)
    dates = [d["date"] for d in client.get("/api/garage-days", headers=h).json()]
    assert dates == ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17"]

    # Si el usuario quita un día automático, no vuelve a aparecer.
    client.delete("/api/garage-days/2026-10-15", headers=h)
    clock["today"] = dt.date(2026, 10, 18)
    dates = [d["date"] for d in client.get("/api/garage-days", headers=h).json()]
    assert dates == ["2026-10-14", "2026-10-16", "2026-10-17", "2026-10-18"]

    # Cambiar la tarifa: los días pendientes se rellenan antes con la tarifa anterior.
    clock["today"] = dt.date(2026, 10, 19)
    client.put("/api/garage/settings", json={"dailyRate": 7}, headers=h)
    rates = {d["date"]: d["rate"] for d in client.get("/api/garage-days", headers=h).json()}
    assert rates["2026-10-19"] == 5.0
    clock["today"] = dt.date(2026, 10, 20)
    assert client.get("/api/garage/summary", headers=h).json()["days"] == 6
    rates = {d["date"]: d["rate"] for d in client.get("/api/garage-days", headers=h).json()}
    assert rates["2026-10-20"] == 7.0

    # Desactivado, ya no agrega días.
    client.put("/api/garage/settings", json={"autoMark": False}, headers=h)
    clock["today"] = dt.date(2026, 10, 25)
    assert len(client.get("/api/garage-days", headers=h).json()) == 6
