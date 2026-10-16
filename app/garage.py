"""Contadores por día (el garaje y otros): "hoy" en la zona horaria de la app, marcado automático y cuenta."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import GarageCharge, GarageDay, Payment, Tracker, User

ZERO = Decimal("0")


def today() -> dt.date:
    return dt.datetime.now(ZoneInfo(get_settings().app_timezone)).date()


def default_tracker(db: Session, user: User) -> Tracker:
    """El primer contador del usuario; si no tiene, se crea "Mi garaje" (rutas /garage* de versiones anteriores)."""
    tracker = db.scalar(select(Tracker).where(Tracker.owner_id == user.id).order_by(Tracker.created_at).limit(1))
    if tracker is None:
        tracker = Tracker(owner_id=user.id, name="Mi garaje", icon="car")
        db.add(tracker)
        db.commit()
    return tracker


def backfill_auto_days(db: Session, tracker: Tracker) -> None:
    """Si el marcado automático está activo, agrega los días que faltan hasta hoy.

    Solo rellena desde el día siguiente a `auto_filled_until`: los días que el
    usuario haya quitado a mano no vuelven a aparecer.
    """
    if not tracker.auto_mark:
        return
    current = today()
    start = (tracker.auto_filled_until or current - dt.timedelta(days=1)) + dt.timedelta(days=1)
    if start > current:
        return

    existing = set(
        db.scalars(
            select(GarageDay.date).where(
                GarageDay.tracker_id == tracker.id, GarageDay.date >= start, GarageDay.date <= current
            )
        )
    )
    day = start
    while day <= current:
        if day not in existing:
            db.add(GarageDay(tracker_id=tracker.id, user_id=tracker.owner_id, date=day, rate=tracker.daily_rate))
        day += dt.timedelta(days=1)
    tracker.auto_filled_until = current
    db.commit()


def summary(db: Session, tracker: Tracker, until: dt.date) -> dict:
    """Cuenta hasta `until` (incluido). Los días futuros marcados no cuentan todavía."""
    days_query = select(
        func.count(GarageDay.id),
        func.count(GarageDay.id).filter(GarageDay.rate.is_(None)),
        func.coalesce(func.sum(GarageDay.rate), ZERO),
    ).where(GarageDay.tracker_id == tracker.id, GarageDay.date <= until)
    days, days_without_rate, days_total = db.execute(days_query).one()

    charges_total = db.scalar(
        select(func.coalesce(func.sum(GarageCharge.amount), ZERO))
        .join(GarageDay, GarageCharge.day_id == GarageDay.id)
        .where(GarageDay.tracker_id == tracker.id, GarageDay.date <= until)
    )
    paid = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), ZERO)).where(
            Payment.tracker_id == tracker.id, Payment.date <= until
        )
    )

    days_total, charges_total, paid = (Decimal(str(v)) for v in (days_total, charges_total, paid))
    total = days_total + charges_total
    return {
        "until": until,
        "daily_rate": float(tracker.daily_rate) if tracker.daily_rate is not None else None,
        "days": days,
        "days_without_rate": days_without_rate,
        "days_total": float(days_total),
        "charges_total": float(charges_total),
        "total": float(total),
        "paid": float(paid),
        "pending": float(total - paid),
    }
