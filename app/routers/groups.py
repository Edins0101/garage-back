"""Grupos (Familia, Roomies…): se comparte una lista, una sección o un contador con el grupo
y lo ven todos sus integrantes, también quienes entren después."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.auth import CurrentUser, Db
from app.models import Checklist, Group, GroupMember, GroupShare, Space, Tracker, User
from app.permissions import Access, access_level, my_group_ids
from app.reminders import KIND_LABELS
from app.schemas import GroupIn, GroupItemOut, GroupMemberIn, GroupMemberOut, GroupOut, GroupShareIn, InviteOut, JoinOut

router = APIRouter(tags=["grupos"])


def _owner_name(item) -> str:
    # Las listas no cargan al dueño como relación.
    owner = getattr(item, "owner", None)
    if owner is None:
        from sqlalchemy.orm import object_session

        owner = object_session(item).get(User, item.owner_id)
    return owner.name


def _item_out(share: GroupShare) -> GroupItemOut:
    if share.checklist is not None:
        item, kind, title = share.checklist, share.checklist.kind, share.checklist.title
        type_ = "list"
    elif share.space is not None:
        item, kind, title = share.space, share.space.kind, KIND_LABELS[share.space.kind]
        type_ = "space"
    else:
        item, kind, title = share.tracker, share.tracker.icon, share.tracker.name
        type_ = "tracker"
    return GroupItemOut(
        type=type_, id=item.id, title=title, kind=kind, owner_id=item.owner_id, owner_name=_owner_name(item), role=share.role
    )


def _group_out(group: Group, user: User) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        owner_id=group.owner_id,
        owner_name=group.owner.name,
        role="owner" if group.owner_id == user.id else "member",
        members=group.members,
        shared=[_item_out(s) for s in group.shares],
        created_at=group.created_at,
    )


def _get_group(db, group_id: str, user: User, owner: bool = False) -> Group:
    """404 si no estoy en el grupo; 403 si hace falta ser el dueño."""
    group = db.get(Group, group_id)
    if group is None or user.id not in group.user_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El grupo no existe")
    if owner and group.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo quien creó el grupo puede hacer esto")
    return group


def join_group(db, user: User, group_id: str) -> JoinOut:
    """Con el código se entra al grupo y se ve todo lo que ya está compartido con él."""
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código inválido o vencido")
    if user.id not in group.user_ids:
        member = next((m for m in group.members if m.email == user.email), None)
        if member is None:
            group.members.append(GroupMember(email=user.email, name=user.name, user_id=user.id, status="accepted"))
        else:
            member.user_id, member.status, member.name = user.id, "accepted", member.name or user.name
        db.commit()
    return JoinOut(type="group", group_id=group.id)


# ---------------------------------------------------------------- grupos

@router.get("/groups", response_model=list[GroupOut])
def groups(user: CurrentUser, db: Db):
    """Mis grupos (primero los que creé) con sus integrantes y lo compartido."""
    found = db.scalars(select(Group).where(Group.id.in_(my_group_ids(user)))).all()
    found = sorted(found, key=lambda g: (g.owner_id != user.id, g.created_at))
    return [_group_out(g, user) for g in found]


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(body: GroupIn, user: CurrentUser, db: Db):
    group = Group(owner_id=user.id, name=body.name.strip())
    db.add(group)
    db.commit()
    db.refresh(group)
    return _group_out(group, user)


@router.patch("/groups/{group_id}", response_model=GroupOut)
def rename_group(group_id: str, body: GroupIn, user: CurrentUser, db: Db):
    group = _get_group(db, group_id, user, owner=True)
    group.name = body.name.strip()
    db.commit()
    db.refresh(group)
    return _group_out(group, user)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: str, user: CurrentUser, db: Db):
    """Se borra el grupo; lo compartido sigue siendo de su dueño, solo deja de verse en el grupo."""
    db.delete(_get_group(db, group_id, user, owner=True))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/groups/{group_id}/members", response_model=GroupMemberOut)
def add_member(group_id: str, body: GroupMemberIn, user: CurrentUser, db: Db):
    """Agrega por correo. Si la persona ya tiene cuenta, entra de inmediato; si no, al registrarse."""
    group = _get_group(db, group_id, user, owner=True)
    email = str(body.email).lower()
    if email == user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya estás en el grupo")
    member = next((m for m in group.members if m.email == email), None)
    if member is None:
        existing = db.scalar(select(User).where(User.email == email))
        member = GroupMember(
            email=email,
            user_id=existing.id if existing else None,
            name=existing.name if existing else None,
            status="accepted" if existing else "pending",
        )
        group.members.append(member)
        db.commit()
        db.refresh(member)
    return member


@router.delete("/groups/{group_id}/members/{email}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(group_id: str, email: str, user: CurrentUser, db: Db):
    group = _get_group(db, group_id, user)
    email = email.lower()
    # Quien creó el grupo puede quitar a cualquiera; un integrante solo puede salirse.
    if group.owner_id != user.id and email != user.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo quien creó el grupo puede hacer esto")
    for member in [m for m in group.members if m.email == email]:
        group.members.remove(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/groups/{group_id}/invites", response_model=InviteOut)
def create_group_invite(group_id: str, user: CurrentUser, db: Db):
    """Código para entrar al grupo."""
    from app.routers.sharing import _new_invite

    group = _get_group(db, group_id, user, owner=True)
    return _new_invite(db, user, group_id=group.id)


# ---------------------------------------------------------------- compartir con un grupo

_TARGETS = {
    "lists": (Checklist, "list_id", "La lista no existe"),
    "spaces": (Space, "space_id", "La sección no existe"),
    "trackers": (Tracker, "tracker_id", "El calendario no existe"),
}


def _owned_item(db, target: str, item_id: str, user: User):
    model, _, missing = _TARGETS[target]
    item = db.get(model, item_id)
    level = access_level(item, user) if item else Access.NONE
    if level == Access.NONE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, missing)
    if level < Access.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el dueño puede compartirlo con un grupo")
    return item


def _share_routes(target: str) -> None:
    _, column, _ = _TARGETS[target]

    def share(item_id: str, group_id: str, body: GroupShareIn, user: CurrentUser, db: Db):
        """Comparte con el grupo (o cambia el permiso). Hay que estar en el grupo."""
        item = _owned_item(db, target, item_id, user)
        group = _get_group(db, group_id, user)
        current = next((s for s in item.group_shares if s.group_id == group.id), None)
        if current is None:
            item.group_shares.append(GroupShare(group_id=group.id, role=body.role, **{column: item.id}))
        else:
            current.role = body.role
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def unshare(item_id: str, group_id: str, user: CurrentUser, db: Db):
        item = _owned_item(db, target, item_id, user)
        for current in [s for s in item.group_shares if s.group_id == group_id]:
            item.group_shares.remove(current)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    path = f"/{target}/{{item_id}}/groups/{{group_id}}"
    router.add_api_route(path, share, methods=["PUT"], status_code=status.HTTP_204_NO_CONTENT, name=f"share_{target}")
    router.add_api_route(
        path, unshare, methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT, name=f"unshare_{target}"
    )


for _target in _TARGETS:
    _share_routes(_target)
