"""Reglas de acceso a las listas (ver docs/API.md → Reglas de negocio)."""

from enum import IntEnum

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Checklist, User


class Access(IntEnum):
    NONE = 0
    VIEWER = 1
    EDITOR = 2
    OWNER = 3


def access_level(checklist: Checklist, user: User) -> Access:
    if checklist.owner_id == user.id:
        return Access.OWNER
    for member in checklist.members:
        if member.user_id == user.id:
            return Access.EDITOR if member.role == "editor" else Access.VIEWER
    return Access.NONE


def get_list(db: Session, list_id: str, user: User, required: Access = Access.VIEWER) -> Checklist:
    """Devuelve la lista si el usuario tiene al menos el acceso pedido.

    Si no tiene ningún acceso responde 404 (no revela que la lista existe).
    """
    checklist = db.get(Checklist, list_id)
    level = access_level(checklist, user) if checklist else Access.NONE
    if level == Access.NONE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La lista no existe")
    if level < required:
        message = {
            Access.EDITOR: "Solo puedes ver esta lista, no editarla",
            Access.OWNER: "Solo el dueño de la lista puede hacer esto",
        }[required]
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)
    return checklist
