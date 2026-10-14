"""Catálogo de productos y fotos (ver garaje-android/docs/PLAN-FOTOS.md)."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth import CurrentUser, Db
from app.catalog import delete_object, search_products, upload_prefix, verify_upload
from app.models import Product
from app.permissions import Access, get_list
from app.schemas import ImageIn, ItemOut, ProductOut, UploadIn, UploadOut
from app.storage import require_storage

router = APIRouter(tags=["fotos"])

_EXTENSIONS = {"image/jpeg": "jpg", "image/webp": "webp", "image/png": "png"}


@router.get("/lists/{list_id}/products", response_model=list[ProductOut])
def list_products(list_id: str, user: CurrentUser, db: Db, q: str = ""):
    """Autocompletar: productos del catálogo del dueño de la lista."""
    checklist = get_list(db, list_id, user)
    return search_products(db, checklist.owner_id, q)


@router.post("/uploads", response_model=UploadOut)
def create_upload(body: UploadIn, user: CurrentUser, db: Db):
    """Enlace temporal (10 min) para subir una foto directo al almacenamiento.

    Después hay que adjuntarla con PUT …/image { key }; si no, queda huérfana.
    """
    checklist = get_list(db, body.list_id, user, Access.EDITOR)
    storage = require_storage()
    key = f"{upload_prefix(checklist.owner_id)}{uuid.uuid4()}.{_EXTENSIONS[body.content_type]}"
    return UploadOut(upload_url=storage.presign_put(key, body.content_type), key=key, content_type=body.content_type)


def _apply_image(db, owner_id: str, target, body: ImageIn, allow_url: bool) -> None:
    """Pone la foto (subida o URL) en un producto o elemento y borra la anterior."""
    if bool(body.key) == bool(body.url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envía la foto subida o una URL (solo una)")
    if body.url and not allow_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La foto propia del elemento debe subirse")
    old_key = target.image_key
    if body.key:
        target.image_size = verify_upload(db, owner_id, body.key)
        target.image_key = body.key
        if allow_url:
            target.image_url = None
    else:
        target.image_url = body.url
        target.image_key = None
        target.image_size = None
    db.commit()
    if old_key and old_key != target.image_key:
        delete_object(old_key)


def _get_product(db, checklist, product_id: str) -> Product:
    product = db.get(Product, product_id)
    if product is None or product.owner_id != checklist.owner_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El producto no existe")
    return product


@router.put("/lists/{list_id}/products/{product_id}/image", response_model=ProductOut)
def set_product_image(list_id: str, product_id: str, body: ImageIn, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    product = _get_product(db, checklist, product_id)
    _apply_image(db, checklist.owner_id, product, body, allow_url=True)
    db.refresh(product)
    return product


@router.delete("/lists/{list_id}/products/{product_id}/image", response_model=ProductOut)
def remove_product_image(list_id: str, product_id: str, user: CurrentUser, db: Db):
    checklist = get_list(db, list_id, user, Access.EDITOR)
    product = _get_product(db, checklist, product_id)
    old_key = product.image_key
    product.image_key = product.image_url = product.image_size = None
    db.commit()
    delete_object(old_key)
    return product


def _get_item(checklist, item_id: str):
    item = next((i for i in checklist.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El elemento no existe")
    return item


@router.put("/lists/{list_id}/items/{item_id}/image", response_model=ItemOut)
def set_item_image(list_id: str, item_id: str, body: ImageIn, user: CurrentUser, db: Db):
    """Foto propia del elemento (reemplaza la del producto solo en este elemento)."""
    checklist = get_list(db, list_id, user, Access.EDITOR)
    item = _get_item(checklist, item_id)
    _apply_image(db, checklist.owner_id, item, body, allow_url=False)
    db.refresh(item)
    return item


@router.delete("/lists/{list_id}/items/{item_id}/image", response_model=ItemOut)
def remove_item_image(list_id: str, item_id: str, user: CurrentUser, db: Db):
    """Quita la foto propia: el elemento vuelve a mostrar la del producto."""
    checklist = get_list(db, list_id, user, Access.EDITOR)
    item = _get_item(checklist, item_id)
    old_key = item.image_key
    item.image_key = item.image_size = None
    db.commit()
    delete_object(old_key)
    db.refresh(item)
    return item
