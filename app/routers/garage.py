"""Contadores por día (garaje, niñera, expreso, días trabajados…).

Rutas nuevas: /trackers y /trackers/{id}/… (ver garaje-android/docs/API.md → Contadores).
Las rutas /garage*, /garage-days y /payments de versiones anteriores de la app siguen
funcionando sobre el primer contador del usuario (que se crea como "Mi garaje" si no hay).
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, or_, select, update

from app.auth import CurrentUser, Db
from app.garage import backfill_auto_days, default_tracker, paid_until, summary, today
from app.models import GarageCharge, GarageDay, GroupShare, Payment, Tracker, TrackerMember, User
from app.permissions import Access, access_level, get_list, shared_by_groups
from app.push import device_tokens, recipients, send_push, tracker_payment_push
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
    TrackerIn,
    TrackerOut,
    TrackerPatchIn,
)

router = APIRouter(tags=["contadores"])

From = Annotated[dt.date | None, Query(alias="from")]


def _legacy_tracker(user: CurrentUser, db: Db) -> Tracker:
    return default_tracker(db, user)


def _tracker_access(required: Access):
    """Dependencia: el contador de la ruta, si el usuario tiene al menos ese permiso.

    Sin acceso responde 404 (no revela que existe); con acceso insuficiente, 403.
    """

    def dependency(tracker_id: str, user: CurrentUser, db: Db) -> Tracker:
        tracker = db.get(Tracker, tracker_id)
        level = access_level(tracker, user) if tracker else Access.NONE
        if level == Access.NONE:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "El calendario no existe")
        if level < required:
            message = {
                Access.EDITOR: "Solo puedes ver este calendario, no editarlo",
                Access.OWNER: "Solo el dueño del calendario puede hacer esto",
            }[required]
            raise HTTPException(status.HTTP_403_FORBIDDEN, message)
        return tracker

    return dependency


Legacy = Annotated[Tracker, Depends(_legacy_tracker)]
#: Ver (viewer), editar días/cargos/pagos (editor) y configurar o compartir (dueño).
ByPath = Annotated[Tracker, Depends(_tracker_access(Access.VIEWER))]
Editable = Annotated[Tracker, Depends(_tracker_access(Access.EDITOR))]
Owned = Annotated[Tracker, Depends(_tracker_access(Access.OWNER))]

_ROLES = {Access.OWNER: "owner", Access.EDITOR: "editor", Access.VIEWER: "viewer"}


# ---------------------------------------------------------------- lógica común

def _settings_out(tracker: Tracker) -> GarageSettingsOut:
    rate = float(tracker.daily_rate) if tracker.daily_rate is not None else None
    return GarageSettingsOut(daily_rate=rate, auto_mark=tracker.auto_mark, today=today())


def _tracker_out(db, tracker: Tracker, user: User) -> TrackerOut:
    backfill_auto_days(db, tracker)
    settings = _settings_out(tracker)
    return TrackerOut(
        id=tracker.id,
        owner_id=tracker.owner_id,
        owner_name=tracker.owner.name,
        role=_ROLES[access_level(tracker, user)],
        members=tracker.members,
        groups=tracker.group_shares,
        name=tracker.name,
        icon=tracker.icon,
        direction=tracker.direction,
        daily_rate=settings.daily_rate,
        auto_mark=tracker.auto_mark,
        list_id=tracker.list_id,
        today=settings.today,
        summary=GarageSummaryOut(**summary(db, tracker, today())),
        created_at=tracker.created_at,
    )


def _apply_settings(db, tracker: Tracker, sent: set[str], daily_rate, auto_mark, apply_to_days_without_rate: bool):
    # Primero se rellenan los días automáticos pendientes con la tarifa ANTERIOR.
    backfill_auto_days(db, tracker)
    if "daily_rate" in sent:
        tracker.daily_rate = daily_rate
        if daily_rate is not None and apply_to_days_without_rate:
            db.execute(
                update(GarageDay)
                .where(GarageDay.tracker_id == tracker.id, GarageDay.rate.is_(None))
                .values(rate=daily_rate)
            )
    if auto_mark is not None and auto_mark != tracker.auto_mark:
        tracker.auto_mark = auto_mark
        if auto_mark:
            # Empieza a contar desde hoy (no rellena el pasado).
            tracker.auto_filled_until = today() - dt.timedelta(days=1)
    db.commit()
    backfill_auto_days(db, tracker)


def _get_day(db, tracker: Tracker, day: dt.date) -> GarageDay | None:
    return db.scalar(select(GarageDay).where(GarageDay.tracker_id == tracker.id, GarageDay.date == day))


def _new_day(db, tracker: Tracker, day: dt.date) -> GarageDay:
    garage_day = GarageDay(tracker_id=tracker.id, user_id=tracker.owner_id, date=day, rate=tracker.daily_rate)
    db.add(garage_day)
    return garage_day


def _list_days(db, tracker: Tracker, from_: dt.date | None, to: dt.date | None):
    backfill_auto_days(db, tracker)
    query = select(GarageDay).where(GarageDay.tracker_id == tracker.id)
    if from_:
        query = query.where(GarageDay.date >= from_)
    if to:
        query = query.where(GarageDay.date <= to)
    return db.scalars(query.order_by(GarageDay.date)).all()


def _check_open(db, tracker: Tracker, day: dt.date) -> None:
    """409 si el día ya está cubierto por los pagos (hay que borrar el pago para cambiarlo)."""
    closed = paid_until(db, tracker)
    if closed is not None and day <= closed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Ese día ya está pagado (cubierto hasta el {closed:%d/%m/%Y}): no se puede cambiar"
        )


def _set_day(db, tracker: Tracker, day: dt.date, body: DayIn) -> GarageDay:
    """Crea o actualiza el día. Al crearlo toma la tarifa vigente si no se envía otra."""
    _check_open(db, tracker, day)
    garage_day = _get_day(db, tracker, day) or _new_day(db, tracker, day)
    if "note" in body.model_fields_set:
        garage_day.note = (body.note or "").strip() or None
    if "rate" in body.model_fields_set:
        garage_day.rate = body.rate
    db.commit()
    db.refresh(garage_day)
    return garage_day


def _remove_day(db, tracker: Tracker, day: dt.date) -> Response:
    _check_open(db, tracker, day)
    garage_day = _get_day(db, tracker, day)
    if garage_day is not None:
        db.delete(garage_day)  # borra también sus cargos
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _add_charge(db, tracker: Tracker, day: dt.date, body: ChargeIn) -> GarageCharge:
    """Agrega un cargo al día. Si el día no estaba marcado, lo marca."""
    _check_open(db, tracker, day)
    garage_day = _get_day(db, tracker, day)
    if garage_day is None:
        garage_day = _new_day(db, tracker, day)
        db.flush()
    charge = GarageCharge(day_id=garage_day.id, description=body.description.strip(), amount=body.amount)
    db.add(charge)
    db.commit()
    db.refresh(charge)
    return charge


def _remove_charge(db, tracker_ids, charge_id: str) -> Response:
    charge = db.get(GarageCharge, charge_id)
    allowed = set(tracker_ids) if isinstance(tracker_ids, list) else set(db.scalars(tracker_ids))
    if charge is not None and charge.day.tracker_id in allowed:
        _check_open(db, db.get(Tracker, charge.day.tracker_id), charge.day.date)
    days = select(GarageDay.id).where(GarageDay.tracker_id.in_(tracker_ids))
    result = db.execute(delete(GarageCharge).where(GarageCharge.id == charge_id, GarageCharge.day_id.in_(days)))
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El cargo no existe")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _list_payments(db, tracker: Tracker):
    query = (
        select(Payment)
        .where(Payment.tracker_id == tracker.id)
        .order_by(Payment.date.desc(), Payment.created_at.desc())
    )
    return db.scalars(query).all()


def _add_payment(db, tracker: Tracker, body: PaymentIn) -> Payment:
    payment = Payment(
        tracker_id=tracker.id,
        user_id=tracker.owner_id,
        date=body.date,
        amount=body.amount,
        note=(body.note or "").strip() or None,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def _remove_payment(db, tracker_ids, payment_id: str) -> Response:
    result = db.execute(delete(Payment).where(Payment.id == payment_id, Payment.tracker_id.in_(tracker_ids)))
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El pago no existe")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _my_tracker_ids(user):
    return select(Tracker.id).where(Tracker.owner_id == user.id)


# ---------------------------------------------------------------- contadores

@router.get("/trackers", response_model=list[TrackerOut])
def list_trackers(user: CurrentUser, db: Db):
    """Mis contadores y los compartidos conmigo (después), con la cuenta hasta hoy."""
    shared_ids = select(TrackerMember.tracker_id).where(TrackerMember.user_id == user.id)
    group_ids = shared_by_groups(GroupShare.tracker_id, user)
    query = select(Tracker).where(
        or_(Tracker.owner_id == user.id, Tracker.id.in_(shared_ids), Tracker.id.in_(group_ids))
    )
    trackers = sorted(db.scalars(query).all(), key=lambda t: (t.owner_id != user.id, t.created_at))
    return [_tracker_out(db, t, user) for t in trackers]


@router.post("/trackers", response_model=TrackerOut, status_code=status.HTTP_201_CREATED)
def create_tracker(body: TrackerIn, user: CurrentUser, db: Db):
    tracker = Tracker(
        owner_id=user.id,
        name=body.name.strip(),
        icon=body.icon,
        direction=body.direction,
        daily_rate=body.daily_rate,
        auto_mark=body.auto_mark,
        auto_filled_until=today() - dt.timedelta(days=1) if body.auto_mark else None,
        list_id=get_list(db, body.list_id, user).id if body.list_id else None,
    )
    db.add(tracker)
    db.commit()
    db.refresh(tracker)
    return _tracker_out(db, tracker, user)


@router.patch("/trackers/{tracker_id}", response_model=TrackerOut)
def update_tracker(body: TrackerPatchIn, tracker: Owned, user: CurrentUser, db: Db):
    if body.name:
        tracker.name = body.name.strip()
    if body.icon:
        tracker.icon = body.icon
    if body.direction:
        tracker.direction = body.direction
    if "list_id" in body.model_fields_set:
        tracker.list_id = get_list(db, body.list_id, user).id if body.list_id else None
    _apply_settings(db, tracker, body.model_fields_set, body.daily_rate, body.auto_mark, body.apply_to_days_without_rate)
    db.commit()
    db.refresh(tracker)
    return _tracker_out(db, tracker, user)


@router.delete("/trackers/{tracker_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tracker(tracker: Owned, db: Db):
    db.delete(tracker)  # se van sus días, cargos y pagos
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/trackers/{tracker_id}/summary", response_model=GarageSummaryOut)
def tracker_summary(tracker: ByPath, db: Db, until: dt.date | None = None):
    backfill_auto_days(db, tracker)
    return summary(db, tracker, until or today())


@router.get("/trackers/{tracker_id}/days", response_model=list[GarageDayOut])
def tracker_days(tracker: ByPath, db: Db, from_: From = None, to: dt.date | None = None):
    return _list_days(db, tracker, from_, to)


@router.put("/trackers/{tracker_id}/days/{day}", response_model=GarageDayOut)
def tracker_set_day(day: dt.date, body: DayIn, tracker: Editable, db: Db):
    return _set_day(db, tracker, day, body)


@router.delete("/trackers/{tracker_id}/days/{day}", status_code=status.HTTP_204_NO_CONTENT)
def tracker_remove_day(day: dt.date, tracker: Editable, db: Db):
    return _remove_day(db, tracker, day)


@router.post("/trackers/{tracker_id}/days/{day}/charges", response_model=ChargeOut, status_code=status.HTTP_201_CREATED)
def tracker_add_charge(day: dt.date, body: ChargeIn, tracker: Editable, db: Db):
    return _add_charge(db, tracker, day, body)


@router.delete("/trackers/{tracker_id}/charges/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
def tracker_remove_charge(charge_id: str, tracker: Editable, db: Db):
    return _remove_charge(db, [tracker.id], charge_id)


@router.get("/trackers/{tracker_id}/payments", response_model=list[PaymentOut])
def tracker_payments(tracker: ByPath, db: Db):
    return _list_payments(db, tracker)


@router.post("/trackers/{tracker_id}/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def tracker_add_payment(body: PaymentIn, tracker: Editable, user: CurrentUser, db: Db, background: BackgroundTasks):
    payment = _add_payment(db, tracker, body)
    # Avisa a los demás que ven el contador (ej. la niñera se entera del pago).
    tokens = device_tokens(db, recipients(db, tracker, exclude_user_id=user.id))
    background.add_task(send_push, tokens, tracker_payment_push(user, tracker, payment.amount))
    return payment


@router.delete("/trackers/{tracker_id}/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def tracker_remove_payment(payment_id: str, tracker: Editable, db: Db):
    return _remove_payment(db, [tracker.id], payment_id)


# ---------------------------------------------------------------- rutas anteriores (primer contador)

@router.get("/garage/settings", response_model=GarageSettingsOut)
def get_settings_(tracker: Legacy):
    return _settings_out(tracker)


@router.put("/garage/settings", response_model=GarageSettingsOut)
def put_settings(body: GarageSettingsIn, tracker: Legacy, db: Db):
    _apply_settings(db, tracker, body.model_fields_set, body.daily_rate, body.auto_mark, body.apply_to_days_without_rate)
    return _settings_out(tracker)


@router.get("/garage/summary", response_model=GarageSummaryOut)
def get_summary(tracker: Legacy, db: Db, until: dt.date | None = None):
    """Cuánto se debe hasta `until` (por defecto, hoy)."""
    backfill_auto_days(db, tracker)
    return summary(db, tracker, until or today())


@router.get("/garage-days", response_model=list[GarageDayOut])
def list_days(tracker: Legacy, db: Db, from_: From = None, to: dt.date | None = None):
    return _list_days(db, tracker, from_, to)


@router.put("/garage-days/{day}", response_model=GarageDayOut)
def set_day(day: dt.date, body: DayIn, tracker: Legacy, db: Db):
    return _set_day(db, tracker, day, body)


@router.delete("/garage-days/{day}", status_code=status.HTTP_204_NO_CONTENT)
def remove_day(day: dt.date, tracker: Legacy, db: Db):
    return _remove_day(db, tracker, day)


@router.post("/garage-days/{day}/charges", response_model=ChargeOut, status_code=status.HTTP_201_CREATED)
def add_charge(day: dt.date, body: ChargeIn, tracker: Legacy, db: Db):
    return _add_charge(db, tracker, day, body)


@router.delete("/garage-charges/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_charge(charge_id: str, user: CurrentUser, db: Db):
    return _remove_charge(db, _my_tracker_ids(user), charge_id)


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(tracker: Legacy, db: Db):
    return _list_payments(db, tracker)


@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def add_payment(body: PaymentIn, tracker: Legacy, db: Db):
    return _add_payment(db, tracker, body)


@router.delete("/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_payment(payment_id: str, user: CurrentUser, db: Db):
    return _remove_payment(db, _my_tracker_ids(user), payment_id)
