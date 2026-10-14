from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import or_, select

from app.auth import CurrentUser, Db
from app.models import Checklist, ChecklistItem, ListMember, utcnow
from app.permissions import Access, get_list
from app.schemas import ChecklistOut, ItemOut, ItemPatchIn, NewItemIn, NewListIn, TitleIn

router = APIRouter(prefix="/lists", tags=["listas"])


def _touch(checklist: Checklist) -> None:
    """Marca la lista como modificada (ordena "recientes" y avisa cambios a los demás)."""
    checklist.updated_at = utcnow()


@router.get("", response_model=list[ChecklistOut])
def all_lists(user: CurrentUser, db: Db):
    """Listas propias y compartidas conmigo, las más recientes primero."""
    shared_ids = select(ListMember.list_id).where(ListMember.user_id == user.id)
    query = (
        select(Checklist)
        .where(or_(Checklist.owner_id == user.id, Checklist.id.in_(shared_ids)))
        .order_by(Checklist.updated_at.desc())
    )
    return db.scalars(query).all()


@router.post("", response_model=ChecklistOut, status_code=status.HTTP_201_CREATED)
def create_list(body: NewListIn, user: CurrentUser, db: Db):
    checklist = Checklist(title=body.title.strip(), kind=body.kind, owner_id=user.id)
    db.add(checklist)
    db.commit()
    db.refresh(checklist)
    return checklist


@router.get("/{list_id}", response_model=ChecklistOut)
def get_one(list_id: str, user: CurrentUser, db: Db):
    return get_list(db, list_id, user)


@router.patch("/{list_id}", response_model=ChecklistOut)
def rename(list_id: str, body: TitleIn, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    checklist.title = body.title.strip()
    db.commit()
    db.refresh(checklist)
    return checklist


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_list(list_id: str, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.OWNER)
    db.delete(checklist)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- elementos

@router.post("/{list_id}/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def add_item(list_id: str, body: NewItemIn, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escribe algo para agregar")
    item = ChecklistItem(list_id=checklist.id, text=text, quantity=(body.quantity or "").strip() or None)
    db.add(item)
    _touch(checklist)
    db.commit()
    db.refresh(item)
    return item


def _get_item(checklist: Checklist, item_id: str) -> ChecklistItem:
    item = next((i for i in checklist.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El elemento no existe")
    return item


@router.patch("/{list_id}/items/{item_id}", response_model=ItemOut)
def update_item(list_id: str, item_id: str, body: ItemPatchIn, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    item = _get_item(checklist, item_id)
    if body.text is not None:
        item.text = body.text.strip() or item.text
    if body.quantity is not None:
        item.quantity = body.quantity.strip() or None
    if body.done is not None:
        item.done = body.done
        item.done_by = user.id if body.done else None
    _touch(checklist)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{list_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(list_id: str, item_id: str, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    db.delete(_get_item(checklist, item_id))
    _touch(checklist)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{list_id}/items/clear-completed", response_model=ChecklistOut)
def clear_completed(list_id: str, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    for item in [i for i in checklist.items if i.done]:
        checklist.items.remove(item)
    _touch(checklist)
    db.commit()
    db.refresh(checklist)
    return checklist
