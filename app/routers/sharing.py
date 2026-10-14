import secrets
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.auth import CurrentUser, Db
from app.config import get_settings
from app.models import Checklist, Invite, ListMember, User, as_utc, utcnow
from app.permissions import Access, access_level, get_list
from app.schemas import ChecklistOut, InviteIn, InviteOut, JoinIn, MemberOut

router = APIRouter(tags=["compartir"])

# Sin 0/O/1/I para que el código se pueda dictar sin confusiones.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _invite_out(invite: Invite) -> InviteOut:
    return InviteOut(
        code=invite.code,
        url=get_settings().invite_url_base + invite.code,
        list_id=invite.list_id,
        expires_at=invite.expires_at,
    )


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
    now = utcnow()
    current = db.scalar(
        select(Invite).where(Invite.list_id == checklist.id, Invite.expires_at > now).order_by(Invite.expires_at.desc())
    )
    if current:
        return _invite_out(current)

    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if db.get(Invite, code) is None:
            break
    invite_row = Invite(
        code=code,
        list_id=checklist.id,
        created_by=user.id,
        expires_at=now + timedelta(days=get_settings().invite_days),
    )
    db.add(invite_row)
    db.commit()
    return _invite_out(invite_row)


@router.post("/invites/join", response_model=ChecklistOut)
def join(body: JoinIn, user: CurrentUser, db: Db):
    invite_row = db.get(Invite, body.code.strip().upper())
    if invite_row is None or as_utc(invite_row.expires_at) <= utcnow():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código inválido o vencido")
    checklist = db.get(Checklist, invite_row.list_id)
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
    return checklist

