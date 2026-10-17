"""Reglas de acceso a listas, secciones y contadores (ver docs/API.md → Reglas de negocio)."""

from enum import IntEnum

from fastapi import HTTPException, status
from sqlalchemy import select, union
from sqlalchemy.orm import Session

from app.models import Checklist, Group, GroupMember, GroupShare, User


class Access(IntEnum):
    NONE = 0
    VIEWER = 1
    EDITOR = 2
    OWNER = 3


def _role(role: str) -> Access:
    return Access.EDITOR if role == "editor" else Access.VIEWER


def access_level(item, user: User) -> Access:
    """Sirve para listas, secciones y contadores (todos tienen owner_id, members y group_shares).

    Gana el mayor permiso: el directo (invitación por correo o código) o el de algún grupo donde esté.
    """
    if item.owner_id == user.id:
        return Access.OWNER
    level = Access.NONE
    for member in item.members:
        if member.user_id == user.id:
            level = max(level, _role(member.role))
    for share in getattr(item, "group_shares", []):
        if user.id in share.group.user_ids:
            level = max(level, _role(share.role))
    return level


def my_group_ids(user: User):
    """Consulta con los ids de los grupos donde estoy (como dueño o integrante que aceptó)."""
    return union(
        select(Group.id).where(Group.owner_id == user.id),
        select(GroupMember.group_id).where(GroupMember.user_id == user.id, GroupMember.status == "accepted"),
    )


def shared_by_groups(column, user: User):
    """Ids compartidos con mis grupos; column es GroupShare.list_id, .space_id o .tracker_id."""
    return select(column).where(GroupShare.group_id.in_(my_group_ids(user)), column.is_not(None))


def get_list(db: Session, list_id: str, user: User, required: Access = Access.VIEWER) -> Checklist:
    """Devuelve la lista si el usuario tiene al menos el acceso pedido.

    Si no tiene ningún acceso responde 404 (no revela que la lista existe).
    """
    checklist = db.get(Checklist, list_id)
    level = access_level(checklist, user) if checklist else Access.NONE
    if checklist is not None:
        checklist.my_access = level
    if level == Access.NONE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La lista no existe")
    if level < required:
        message = {
            Access.EDITOR: "Solo puedes ver esta lista, no editarla",
            Access.OWNER: "Solo el dueño de la lista puede hacer esto",
        }[required]
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)
    return checklist
