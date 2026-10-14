import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import delete, select, update

from app.auth import CurrentUser, Db
from app.garage import backfill_auto_days, summary, today
from app.models import GarageCharge, GarageDay, Payment
from app.schemas import (
    ChargeIn,
    ChargeOut,
    DayIn,
    GarageDayOut,
    GarageSettingsIn,
    GarageSettingsOut,
    GarageSummaryOut,
    PaymentIn,
    PaymentOut,
)

router = APIRouter(tags=["garaje"])


# ---------------------------------------------------------------- configuración

def _settings_out(user) -> GarageSettingsOut:
    rate = float(user.garage_daily_rate) if user.garage_daily_rate is not None else None
    return GarageSettingsOut(daily_rate=rate, auto_mark=user.garage_auto_mark, today=today())


@router.get("/garage/settings", response_model=GarageSettingsOut)
def get_settings_(user: CurrentUser):
    return _settings_out(user)


@router.put("/garage/settings", response_model=GarageSettingsOut)
def put_settings(body: GarageSettingsIn, user: CurrentUser, db: Db):
    # Primero se rellenan los días automáticos pendientes con la tarifa ANTERIOR.
    backfill_auto_days(db, user)

    if "daily_rate" in body.model_fields_set:
        user.garage_daily_rate = body.daily_rate
        if body.daily_rate is not None and body.apply_to_days_without_rate:
            db.execute(
                update(GarageDay)
                .where(GarageDay.user_id == user.id, GarageDay.rate.is_(None))
                .values(rate=body.daily_rate)
            )

    if body.auto_mark is not None and body.auto_mark != user.garage_auto_mark:
        user.garage_auto_mark = body.auto_mark
        if body.auto_mark:
            # Empieza a contar desde hoy (no rellena el pasado).
            user.garage_auto_filled_until = today() - dt.timedelta(days=1)
    db.commit()
    backfill_auto_days(db, user)
    return _settings_out(user)


@router.get("/garage/summary", response_model=GarageSummaryOut)
def get_summary(user: CurrentUser, db: Db, until: dt.date | None = None):
    """Cuánto se debe hasta `until` (por defecto, hoy)."""
    backfill_auto_days(db, user)
    return summary(db, user, until or today())


# ---------------------------------------------------------------- días

def _get_day(db, user, day: dt.date) -> GarageDay | None:
    return db.scalar(select(GarageDay).where(GarageDay.user_id == user.id, GarageDay.date == day))


@router.get("/garage-days", response_model=list[GarageDayOut])
def list_days(
    user: CurrentUser,
    db: Db,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: dt.date | None = None,
):
    backfill_auto_days(db, user)
    query = select(GarageDay).where(GarageDay.user_id == user.id)
    if from_:
        query = query.where(GarageDay.date >= from_)
    if to:
        query = query.where(GarageDay.date <= to)
    return db.scalars(query.order_by(GarageDay.date)).all()


@router.put("/garage-days/{day}", response_model=GarageDayOut)
def set_day(day: dt.date, body: DayIn, user: CurrentUser, db: Db):
    """Crea o actualiza el día. Al crearlo toma la tarifa vigente si no se envía otra."""
    garage_day = _get_day(db, user, day)
    if garage_day is None:
        garage_day = GarageDay(user_id=user.id, date=day, rate=user.garage_daily_rate)
        db.add(garage_day)
    if "note" in body.model_fields_set:
        garage_day.note = (body.note or "").strip() or None
    if "rate" in body.model_fields_set:
        garage_day.rate = body.rate
    db.commit()
    db.refresh(garage_day)
    return garage_day


@router.delete("/garage-days/{day}", status_code=status.HTTP_204_NO_CONTENT)
def remove_day(day: dt.date, user: CurrentUser, db: Db):
    garage_day = _get_day(db, user, day)
    if garage_day is not None:
        db.delete(garage_day)  # borra también sus cargos
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- cargos extra

@router.post("/garage-days/{day}/charges", response_model=ChargeOut, status_code=status.HTTP_201_CREATED)
def add_charge(day: dt.date, body: ChargeIn, user: CurrentUser, db: Db):
    """Agrega un cargo al día. Si el día no estaba marcado, lo marca."""
    garage_day = _get_day(db, user, day)
    if garage_day is None:
        garage_day = GarageDay(user_id=user.id, date=day, rate=user.garage_daily_rate)
        db.add(garage_day)
        db.flush()
    charge = GarageCharge(day_id=garage_day.id, description=body.description.strip(), amount=body.amount)
    db.add(charge)
    db.commit()
    db.refresh(charge)
    return charge


@router.delete("/garage-charges/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_charge(charge_id: str, user: CurrentUser, db: Db):
    owned_days = select(GarageDay.id).where(GarageDay.user_id == user.id)
    result = db.execute(delete(GarageCharge).where(GarageCharge.id == charge_id, GarageCharge.day_id.in_(owned_days)))
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El cargo no existe")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- pagos

@router.get("/payments", response_model=list[PaymentOut])
def list_payments(user: CurrentUser, db: Db):
    query = select(Payment).where(Payment.user_id == user.id).order_by(Payment.date.desc(), Payment.created_at.desc())
    return db.scalars(query).all()


@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def add_payment(body: PaymentIn, user: CurrentUser, db: Db):
    payment = Payment(user_id=user.id, date=body.date, amount=body.amount, note=(body.note or "").strip() or None)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.delete("/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_payment(payment_id: str, user: CurrentUser, db: Db):
    result = db.execute(delete(Payment).where(Payment.id == payment_id, Payment.user_id == user.id))
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El pago no existe")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
