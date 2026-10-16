import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import select

from app.auth import CurrentUser, Db
from app.config import get_settings
from app.models import Checklist, Invite, ListMember, Space, SpaceMember, Tracker, TrackerMember, User, as_utc, utcnow
from app.push import device_tokens, member_joined_push, recipients, send_push
from app.permissions import Access, access_level, get_list
from app.reminders import get_space
from app.schemas import ChecklistOut, InviteIn, InviteOut, JoinIn, JoinOut, MemberOut

router = APIRouter(tags=["compartir"])

# Sin 0/O/1/I para que el código se pueda dictar sin confusiones.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _invite_out(invite: Invite) -> InviteOut:
    return InviteOut(
        code=invite.code,
        url=get_settings().invite_url_base + invite.code,
        list_id=invite.list_id,
        space_id=invite.space_id,
        tracker_id=invite.tracker_id,
        expires_at=invite.expires_at,
    )


def _new_invite(
    db, user: User, *, list_id: str | None = None, space_id: str | None = None, tracker_id: str | None = None
) -> InviteOut:
    """Código de invitación; reutiliza uno vigente si existe."""
    now = utcnow()
    if list_id:
        target = Invite.list_id == list_id
    elif space_id:
        target = Invite.space_id == space_id
    else:
        target = Invite.tracker_id == tracker_id
    current = db.scalar(select(Invite).where(target, Invite.expires_at > now).order_by(Invite.expires_at.desc()))
    if current:
        return _invite_out(current)
    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if db.get(Invite, code) is None:
            break
    invite_row = Invite(
        code=code,
        list_id=list_id,
        space_id=space_id,
        tracker_id=tracker_id,
        created_by=user.id,
        expires_at=now + timedelta(days=get_settings().invite_days),
    )
    db.add(invite_row)
    db.commit()
    return _invite_out(invite_row)


@router.get("/lists/{list_id}/members", response_model=list[MemberOut])
def members(list_id: str, user: CurrentUser, db: Db):
    return get_list(db, list_id, user).members


@router.post("/lists/{list_id}/members", response_model=MemberOut)
def invite(list_id: str, body: InviteIn, user: CurrentUser, db: Db):
    """Invita por correo. Si la persona ya tiene cuenta, obtiene acceso de inmediato."""
    checklist = get_list(db, list_id, user, Access.OWNER)
    email = str(body.email).lower()
    if email == user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes invitarte a ti mismo")

    member = next((m for m in checklist.members if m.email == email), None)
    if member is None:
        existing = db.scalar(select(User).where(User.email == email))
        member = ListMember(
            email=email,
            role=body.role,
            user_id=existing.id if existing else None,
            name=existing.name if existing else None,
            status="accepted" if existing else "pending",
        )
        checklist.members.append(member)
    else:
        member.role = body.role
    db.commit()
    db.refresh(member)
    return member


@router.delete("/lists/{list_id}/members/{email}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(list_id: str, email: str, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user)
    email = email.lower()
    # El dueño puede quitar a cualquiera; un miembro solo puede salirse él mismo.
    if access_level(checklist, user) != Access.OWNER and email != user.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el dueño de la lista puede hacer esto")
    for member in [m for m in checklist.members if m.email == email]:
        checklist.members.remove(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/lists/{list_id}/invites", response_model=InviteOut)
def create_invite(list_id: str, user: CurrentUser, db: Db):
    """Código de invitación; reutiliza uno vigente si existe."""
    checklist = get_list(db, list_id, user, Access.OWNER)
    return _new_invite(db, user, list_id=checklist.id)


@router.post("/spaces/{space_id}/invites", response_model=InviteOut)
def create_space_invite(space_id: str, user: CurrentUser, db: Db):
    """Código para unirse a toda una sección de recordatorios (ej. los Pagos de la casa)."""
    space = get_space(db, space_id, user, Access.OWNER)
    return _new_invite(db, user, space_id=space.id)


def _valid_invite(db, code: str) -> Invite:
    invite_row = db.get(Invite, code.strip().upper())
    if invite_row is None or as_utc(invite_row.expires_at) <= utcnow():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código inválido o vencido")
    return invite_row


@router.post("/join", response_model=JoinOut)
def join_any(body: JoinIn, user: CurrentUser, db: Db, background: BackgroundTasks):
    """Unirse con un código de lista o de sección. La app abre lo que corresponda."""
    invite_row = _valid_invite(db, body.code)
    if invite_row.list_id:
        checklist = join(body, user, db, background)
        return JoinOut(type="list", list_id=checklist.id)
    if invite_row.tracker_id:
        return _join_tracker(db, user, invite_row.tracker_id)
    space = db.get(Space, invite_row.space_id)
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código inválido o vencido")
    if access_level(space, user) == Access.NONE:
        member = next((m for m in space.members if m.email == user.email), None)
        if member is None:
            space.members.append(
                SpaceMember(email=user.email, name=user.name, user_id=user.id, role="editor", status="accepted")
            )
        else:
            member.user_id, member.status = user.id, "accepted"
        db.commit()
    return JoinOut(type="space", space_id=space.id, kind=space.kind)


def _join_tracker(db, user: User, tracker_id: str) -> JoinOut:
    """Con el código se entra como "solo ver" (ej. la niñera); el dueño puede darle edición por correo."""
    tracker = db.get(Tracker, tracker_id)
    if tracker is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código inválido o vencido")
    if access_level(tracker, user) == Access.NONE:
        member = next((m for m in tracker.members if m.email == user.email), None)
        if member is None:
            tracker.members.append(
                TrackerMember(email=user.email, name=user.name, user_id=user.id, role="viewer", status="accepted")
            )
        else:
            member.user_id, member.status = user.id, "accepted"
        db.commit()
    return JoinOut(type="tracker", tracker_id=tracker.id)


# ---------------------------------------------------------------- contadores

def _get_tracker(db, tracker_id: str, user: User, required: Access) -> Tracker:
    tracker = db.get(Tracker, tracker_id)
    level = access_level(tracker, user) if tracker else Access.NONE
    if level == Access.NONE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El contador no existe")
    if level < required:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el dueño del contador puede hacer esto")
    return tracker


@router.post("/trackers/{tracker_id}/members", response_model=MemberOut)
def invite_to_tracker(tracker_id: str, body: InviteIn, user: CurrentUser, db: Db):
    """Invita por correo con "puede editar" o "solo ver". Si ya tiene cuenta, accede de inmediato."""
    tracker = _get_tracker(db, tracker_id, user, Access.OWNER)
    email = str(body.email).lower()
    if email == user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes invitarte a ti mismo")
    member = next((m for m in tracker.members if m.email == email), None)
    if member is None:
        existing = db.scalar(select(User).where(User.email == email))
        member = TrackerMember(
            email=email,
            role=body.role,
            user_id=existing.id if existing else None,
            name=existing.name if existing else None,
            status="accepted" if existing else "pending",
        )
        tracker.members.append(member)
    else:
        member.role = body.role
    db.commit()
    db.refresh(member)
    return member


@router.delete("/trackers/{tracker_id}/members/{email}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_tracker(tracker_id: str, email: str, user: CurrentUser, db: Db):
    tracker = _get_tracker(db, tracker_id, user, Access.VIEWER)
    email = email.lower()
    # El dueño puede quitar a cualquiera; un miembro solo puede salirse él mismo.
    if access_level(tracker, user) != Access.OWNER and email != user.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el dueño del contador puede hacer esto")
    for member in [m for m in tracker.members if m.email == email]:
        tracker.members.remove(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/trackers/{tracker_id}/invites", response_model=InviteOut)
def create_tracker_invite(tracker_id: str, user: CurrentUser, db: Db):
    """Código para ver el contador (entra como "solo ver")."""
    tracker = _get_tracker(db, tracker_id, user, Access.OWNER)
    return _new_invite(db, user, tracker_id=tracker.id)


@router.post("/invites/join", response_model=ChecklistOut)
def join(body: JoinIn, user: CurrentUser, db: Db, background: BackgroundTasks):
    """Solo listas (versiones anteriores de la app). Las nuevas usan POST /join."""
    invite_row = _valid_invite(db, body.code)
    checklist = db.get(Checklist, invite_row.list_id) if invite_row.list_id else None
    if checklist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código inválido o vencido")

    if access_level(checklist, user) == Access.NONE:
        member = next((m for m in checklist.members if m.email == user.email), None)
        if member is None:
            checklist.members.append(
                ListMember(email=user.email, name=user.name, user_id=user.id, role="editor", status="accepted")
            )
        else:
            member.user_id, member.status = user.id, "accepted"
        db.commit()
        db.refresh(checklist)
        tokens = device_tokens(db, recipients(db, checklist, exclude_user_id=user.id))
        background.add_task(send_push, tokens, member_joined_push(user, checklist))
    return checklist

