import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import delete, select

from app.auth import CurrentUser, Db
from app.models import GarageDay
from app.schemas import GarageDayOut, NoteIn

router = APIRouter(prefix="/garage-days", tags=["garaje"])


@router.get("", response_model=list[GarageDayOut])
def list_days(
    user: CurrentUser,
    db: Db,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: dt.date | None = None,
):
    query = select(GarageDay).where(GarageDay.user_id == user.id)
    if from_:
        query = query.where(GarageDay.date >= from_)
    if to:
        query = query.where(GarageDay.date <= to)
    return db.scalars(query.order_by(GarageDay.date)).all()


@router.put("/{day}", response_model=GarageDayOut)
def set_day(day: dt.date, body: NoteIn, user: CurrentUser, db: Db):
    """Crea o actualiza el día (idempotente)."""
    note = (body.note or "").strip() or None
    garage_day = db.scalar(select(GarageDay).where(GarageDay.user_id == user.id, GarageDay.date == day))
    if garage_day is None:
        garage_day = GarageDay(user_id=user.id, date=day, note=note)
        db.add(garage_day)
    else:
        garage_day.note = note
    db.commit()
    db.refresh(garage_day)
    return garage_day


@router.delete("/{day}", status_code=status.HTTP_204_NO_CONTENT)
def remove_day(day: dt.date, user: CurrentUser, db: Db):
    db.execute(delete(GarageDay).where(GarageDay.user_id == user.id, GarageDay.date == day))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
