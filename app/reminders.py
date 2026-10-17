"""Recordatorios: repetición de fechas y acceso a las secciones (ver garaje-android/docs/PLAN-RECORDATORIOS.md)."""

import calendar
import datetime as dt

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Reminder, Space, User
from app.permissions import Access, access_level

KIND_LABELS = {"payments": "Pagos", "home": "Mi hogar", "car": "Mi carro", "other": "Recordatorios"}
KINDS = tuple(KIND_LABELS)


def add_months(date: dt.date, months: int, anchor_day: int | None = None) -> dt.date:
    """Suma meses respetando el día original: 31 ene + 1 mes = 28 feb; + 2 meses = 31 mar."""
    index = date.month - 1 + months
    year, month = date.year + index // 12, index % 12 + 1
    day = min(anchor_day or date.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def advance(due: dt.date, every: int, unit: str, anchor_day: int | None) -> dt.date:
    """Siguiente vencimiento después de `due`."""
    match unit:
        case "day":
            return due + dt.timedelta(days=every)
        case "week":
            return due + dt.timedelta(weeks=every)
        case "month":
            return add_months(due, every, anchor_day)
        case "year":
            return add_months(due, every * 12, anchor_day)
    raise ValueError(unit)


#: Por defecto: los pagos tienen fecha fija; los mantenimientos se cuentan desde que se hicieron.
DEFAULT_COUNT_FROM = {"payments": "due", "home": "done", "car": "done", "other": "due"}


def mark_done(reminder: Reminder, done_on: dt.date) -> None:
    """Pasa al siguiente vencimiento. Termina si es de una sola vez o si el siguiente cae después de `ends_on`."""
    if not (reminder.every and reminder.unit):
        reminder.finished = True
        return
    if reminder.count_from == "done":
        following = advance(done_on, reminder.every, reminder.unit, done_on.day)
    else:
        following = advance(reminder.next_due, reminder.every, reminder.unit, reminder.anchor_day)
    if reminder.ends_on is not None and following > reminder.ends_on:
        # Era el último del rango (ej. la pastilla del 18 al 25): queda hecho en su última fecha.
        reminder.finished = True
        return
    if reminder.count_from == "done":
        reminder.anchor_day = done_on.day
    reminder.next_due = following


def own_space(db: Session, user: User, kind: str) -> Space:
    """La sección del usuario para ese tipo; se crea la primera vez."""
    space = db.scalar(select(Space).where(Space.owner_id == user.id, Space.kind == kind))
    if space is None:
        space = Space(owner_id=user.id, kind=kind)
        db.add(space)
        db.flush()
    return space


def get_space(db: Session, space_id: str, user: User, required: Access = Access.VIEWER) -> Space:
    """Igual que get_list: 404 si no tiene acceso, 403 si no le alcanza el permiso."""
    space = db.get(Space, space_id)
    level = access_level(space, user) if space else Access.NONE
    if space is not None:
        space.my_access = level
    if level == Access.NONE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La sección no existe")
    if level < required:
        message = {
            Access.EDITOR: "Solo puedes ver esta sección, no editarla",
            Access.OWNER: "Solo el dueño de la sección puede hacer esto",
        }[required]
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)
    return space


def get_reminder(db: Session, reminder_id: str, user: User, required: Access = Access.VIEWER) -> Reminder:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or access_level(reminder.space, user) == Access.NONE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El recordatorio no existe")
    get_space(db, reminder.space_id, user, required)
    return reminder
