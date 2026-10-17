from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import or_, select

from app.auth import CurrentUser, Db
from app.catalog import delete_object, find_or_create_product
from app.push import device_tokens, item_added_push, recipients, send_push
from app.models import Checklist, ChecklistItem, GroupShare, ListMember, utcnow
from app.permissions import Access, access_level, get_list, shared_by_groups
from app.schemas import ChecklistOut, ItemOut, ItemPatchIn, NewItemIn, NewListIn, TitleIn

router = APIRouter(prefix="/lists", tags=["listas"])


def _touch(checklist: Checklist) -> None:
    """Marca la lista como modificada (ordena "recientes" y avisa cambios a los demás)."""
    checklist.updated_at = utcnow()


@router.get("", response_model=list[ChecklistOut])
def all_lists(user: CurrentUser, db: Db):
    """Listas propias y compartidas conmigo, las más recientes primero."""
    shared_ids = select(ListMember.list_id).where(ListMember.user_id == user.id)
    group_ids = shared_by_groups(GroupShare.list_id, user)
    query = (
        select(Checklist)
        .where(or_(Checklist.owner_id == user.id, Checklist.id.in_(shared_ids), Checklist.id.in_(group_ids)))
        .order_by(Checklist.updated_at.desc())
    )
    found = db.scalars(query).all()
    for checklist in found:
        checklist.my_access = access_level(checklist, user)
    return found


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
    keys = [i.image_key for i in checklist.items if i.image_key]
    db.delete(checklist)
    db.commit()
    for key in keys:  # las fotos propias de los elementos se van con la lista (las del catálogo quedan)
        delete_object(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- elementos

@router.post("/{list_id}/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def add_item(list_id: str, body: NewItemIn, user: CurrentUser, db: Db, background: BackgroundTasks):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escribe algo para agregar")
    product = find_or_create_product(db, checklist.owner_id, text)
    item = ChecklistItem(
        list_id=checklist.id,
        text=text,
        quantity=(body.quantity or "").strip() or None,
        product_id=product.id,
    )
    db.add(item)
    _touch(checklist)
    db.commit()
    db.refresh(item)
    # Avisar a los demás miembros de la lista (no a quien agregó).
    tokens = device_tokens(db, recipients(db, checklist, exclude_user_id=user.id))
    background.add_task(send_push, tokens, item_added_push(user, checklist, item.text))
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
    if body.text is not None and body.text.strip() and body.text.strip() != item.text:
        item.text = body.text.strip()
        # Otro nombre = otro producto del catálogo.
        item.product_id = find_or_create_product(db, checklist.owner_id, item.text).id
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
    item = _get_item(checklist, item_id)
    key = item.image_key
    db.delete(item)
    _touch(checklist)
    db.commit()
    delete_object(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{list_id}/items/clear-completed", response_model=ChecklistOut)
def clear_completed(list_id: str, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    keys = []
    for item in [i for i in checklist.items if i.done]:
        keys.append(item.image_key)
        checklist.items.remove(item)
    _touch(checklist)
    db.commit()
    for key in keys:
        delete_object(key)
    db.refresh(checklist)
    return checklist
