"""Recordatorios (Pagos, Mi hogar, Mi carro) y sus secciones compartidas.

Ver garaje-android/docs/PLAN-RECORDATORIOS.md y docs/API.md → Recordatorios.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response, status
from sqlalchemy import or_, select

from app.auth import CurrentUser, Db
from app.models import Reminder, ReminderLog, Space, SpaceMember, User
from app.permissions import Access, access_level
from app.push import device_tokens, recipients, reminder_added_push, reminder_done_push, send_push
from app.garage import today
from app.reminders import DEFAULT_COUNT_FROM, get_reminder, get_space, mark_done, own_space
from app.schemas import (
    DoneIn,
    InviteIn,
    MemberOut,
    NewReminderIn,
    ReminderLogOut,
    ReminderOut,
    ReminderPatchIn,
    SpaceKind,
    SpaceOut,
)

router = APIRouter(tags=["recordatorios"])


def _accessible_spaces(db: Db, user: User, kind: str) -> list[Space]:
    """La sección propia (se crea si no existe) y las compartidas conmigo, de ese tipo."""
    own = own_space(db, user, kind)
    db.commit()
    shared_ids = select(SpaceMember.space_id).where(SpaceMember.user_id == user.id)
    query = select(Space).where(Space.kind == kind, or_(Space.id == own.id, Space.id.in_(shared_ids)))
    return sorted(db.scalars(query).all(), key=lambda s: (s.owner_id != user.id, s.owner.name.lower()))


def _notify(db: Db, background: BackgroundTasks, space: Space, actor: User, push) -> None:
    tokens = device_tokens(db, recipients(db, space, exclude_user_id=actor.id))
    background.add_task(send_push, tokens, push)


# ---------------------------------------------------------------- secciones

@router.get("/spaces", response_model=list[SpaceOut])
def spaces(user: CurrentUser, db: Db, kind: SpaceKind = Query()):
    return _accessible_spaces(db, user, kind)


@router.post("/spaces/{space_id}/members", response_model=MemberOut)
def invite_member(space_id: str, body: InviteIn, user: CurrentUser, db: Db):
    """Invita por correo a toda la sección. Si la persona ya tiene cuenta, obtiene acceso de inmediato."""
    space = get_space(db, space_id, user, Access.OWNER)
    email = str(body.email).lower()
    if email == user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes invitarte a ti mismo")
    member = next((m for m in space.members if m.email == email), None)
    if member is None:
        existing = db.scalar(select(User).where(User.email == email))
        member = SpaceMember(
            email=email,
            role=body.role,
            user_id=existing.id if existing else None,
            name=existing.name if existing else None,
            status="accepted" if existing else "pending",
        )
        space.members.append(member)
    else:
        member.role = body.role
    db.commit()
    db.refresh(member)
    return member


@router.delete("/spaces/{space_id}/members/{email}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(space_id: str, email: str, user: CurrentUser, db: Db):
    space = get_space(db, space_id, user)
    email = email.lower()
    # El dueño puede quitar a cualquiera; un miembro solo puede salirse él mismo.
    if access_level(space, user) != Access.OWNER and email != user.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el dueño de la sección puede hacer esto")
    for member in [m for m in space.members if m.email == email]:
        space.members.remove(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- recordatorios

@router.get("/reminders", response_model=list[ReminderOut])
def reminders(user: CurrentUser, db: Db, kind: SpaceKind = Query()):
    """Todos los recordatorios de ese tipo que puedo ver, por fecha de vencimiento."""
    ids = [s.id for s in _accessible_spaces(db, user, kind)]
    query = select(Reminder).where(Reminder.space_id.in_(ids)).order_by(Reminder.next_due, Reminder.title)
    return db.scalars(query).all()


@router.post("/reminders", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
def create_reminder(body: NewReminderIn, user: CurrentUser, db: Db, background: BackgroundTasks):
    if body.space_id:
        space = get_space(db, body.space_id, user, Access.EDITOR)
        if space.kind != body.kind:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "La sección no es de ese tipo")
    else:
        space = own_space(db, user, body.kind)
    reminder = Reminder(
        space_id=space.id,
        title=body.title.strip(),
        amount=body.amount,
        every=body.every,
        unit=body.unit,
        anchor_day=body.next_due.day,
        next_due=body.next_due,
        notify_days_before=body.notify_days_before,
        count_from=body.count_from or DEFAULT_COUNT_FROM[body.kind],
        note=(body.note or "").strip() or None,
        created_by=user.id,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    _notify(db, background, space, user, reminder_added_push(user, reminder))
    return reminder


@router.patch("/reminders/{reminder_id}", response_model=ReminderOut)
def update_reminder(reminder_id: str, body: ReminderPatchIn, user: CurrentUser, db: Db):
    reminder = get_reminder(db, reminder_id, user, Access.EDITOR)
    sent = body.model_fields_set
    if {"every", "unit"} & sent:
        every = body.every if "every" in sent else reminder.every
        unit = body.unit if "unit" in sent else reminder.unit
        if (every is None) != (unit is None):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indica cada cuánto se repite (número y unidad) o ninguno de los dos")
        reminder.every, reminder.unit = every, unit
    if "title" in sent and body.title:
        reminder.title = body.title.strip()
    if "amount" in sent:
        reminder.amount = body.amount
    if "note" in sent:
        reminder.note = (body.note or "").strip() or None
    if "notify_days_before" in sent and body.notify_days_before is not None:
        reminder.notify_days_before = body.notify_days_before
    if "count_from" in sent and body.count_from:
        reminder.count_from = body.count_from
    if "next_due" in sent and body.next_due:
        reminder.next_due = body.next_due
        reminder.anchor_day = body.next_due.day
        reminder.finished = False
    db.commit()
    db.refresh(reminder)
    return reminder


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(reminder_id: str, user: CurrentUser, db: Db):
    reminder = get_reminder(db, reminder_id, user, Access.EDITOR)
    db.delete(reminder)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reminders/{reminder_id}/done", response_model=ReminderOut)
def done(reminder_id: str, body: DoneIn, user: CurrentUser, db: Db, background: BackgroundTasks):
    """Ya pagué / hecho: guarda el historial y pasa al siguiente vencimiento."""
    reminder = get_reminder(db, reminder_id, user, Access.EDITOR)
    if reminder.finished:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este recordatorio ya está hecho")
    log = ReminderLog(
        due_date=reminder.next_due,
        amount=body.amount if body.amount is not None else reminder.amount,
        note=(body.note or "").strip() or None,
        done_by=user.id,
        done_by_name=user.name,
    )
    reminder.logs.insert(0, log)
    mark_done(reminder, today())
    db.commit()
    db.refresh(reminder)
    _notify(db, background, reminder.space, user, reminder_done_push(user, reminder))
    return reminder


@router.post("/reminders/{reminder_id}/undo", response_model=ReminderOut)
def undo(reminder_id: str, user: CurrentUser, db: Db):
    """Deshace la última marca: el vencimiento que cubría vuelve a ser el próximo."""
    reminder = get_reminder(db, reminder_id, user, Access.EDITOR)
    if not reminder.logs:
        raise HTTPException(status.HTTP_409_CONFLICT, "No hay nada que deshacer")
    last = reminder.logs[0]
    reminder.next_due = last.due_date
    reminder.anchor_day = last.due_date.day if reminder.count_from == "done" else reminder.anchor_day
    reminder.finished = False
    reminder.logs.remove(last)
    db.commit()
    db.refresh(reminder)
    return reminder


@router.get("/reminders/{reminder_id}/history", response_model=list[ReminderLogOut])
def history(reminder_id: str, user: CurrentUser, db: Db):
    return get_reminder(db, reminder_id, user).logs[:100]
