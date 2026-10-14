"""Lógica del garaje: "hoy" en la zona horaria de la app, marcado automático y cuenta por pagar."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import GarageCharge, GarageDay, Payment, User

ZERO = Decimal("0")


def today() -> dt.date:
    return dt.datetime.now(ZoneInfo(get_settings().app_timezone)).date()


def backfill_auto_days(db: Session, user: User) -> None:
    """Si el marcado automático está activo, agrega los días que faltan hasta hoy.

    Solo rellena desde el día siguiente a `garage_auto_filled_until`: los días que el
    usuario haya quitado a mano no vuelven a aparecer.
    """
    if not user.garage_auto_mark:
        return
    current = today()
    start = (user.garage_auto_filled_until or current - dt.timedelta(days=1)) + dt.timedelta(days=1)
    if start > current:
        return

    existing = set(
        db.scalars(
            select(GarageDay.date).where(
                GarageDay.user_id == user.id, GarageDay.date >= start, GarageDay.date <= current
            )
        )
    )
    day = start
    while day <= current:
        if day not in existing:
            db.add(GarageDay(user_id=user.id, date=day, rate=user.garage_daily_rate))
        day += dt.timedelta(days=1)
    user.garage_auto_filled_until = current
    db.commit()


def summary(db: Session, user: User, until: dt.date) -> dict:
    """Cuenta hasta `until` (incluido). Los días futuros marcados no cuentan todavía."""
    days_query = select(
        func.count(GarageDay.id),
        func.count(GarageDay.id).filter(GarageDay.rate.is_(None)),
        func.coalesce(func.sum(GarageDay.rate), ZERO),
    ).where(GarageDay.user_id == user.id, GarageDay.date <= until)
    days, days_without_rate, days_total = db.execute(days_query).one()

    charges_total = db.scalar(
        select(func.coalesce(func.sum(GarageCharge.amount), ZERO))
        .join(GarageDay, GarageCharge.day_id == GarageDay.id)
        .where(GarageDay.user_id == user.id, GarageDay.date <= until)
    )
    paid = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), ZERO)).where(
            Payment.user_id == user.id, Payment.date <= until
        )
    )

    days_total, charges_total, paid = (Decimal(str(v)) for v in (days_total, charges_total, paid))
    total = days_total + charges_total
    return {
        "until": until,
        "daily_rate": float(user.garage_daily_rate) if user.garage_daily_rate is not None else None,
        "days": days,
        "days_without_rate": days_without_rate,
        "days_total": float(days_total),
        "charges_total": float(charges_total),
        "total": float(total),
        "paid": float(paid),
        "pending": float(total - paid),
    }
