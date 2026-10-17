"""Catálogo de productos y fotos (ver garaje-android/docs/PLAN-FOTOS.md).

El catálogo que usa una lista es el de su DUEÑO: quienes editan una lista compartida
usan y mejoran ese catálogo.
"""

import re
import unicodedata

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Checklist, ChecklistItem, Product
from app.storage import get_storage, require_storage


def normalize(name: str) -> str:
    """"  Leché  " → "leche": minúsculas, sin tildes y con espacios simples."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def find_or_create_product(db: Session, owner_id: str, name: str) -> Product:
    normalized = normalize(name)
    product = db.scalar(select(Product).where(Product.owner_id == owner_id, Product.normalized_name == normalized))
    if product is None:
        product = Product(owner_id=owner_id, name=name.strip(), normalized_name=normalized)
        db.add(product)
        db.flush()
    return product


def search_products(db: Session, owner_id: str, query: str, limit: int = 8) -> list[Product]:
    """Productos que empiezan con lo escrito primero; luego los que lo contienen."""
    q = normalize(query)
    base = select(Product).where(Product.owner_id == owner_id)
    if not q:
        return list(db.scalars(base.order_by(Product.updated_at.desc()).limit(limit)))
    starts = list(db.scalars(base.where(Product.normalized_name.startswith(q)).order_by(Product.name).limit(limit)))
    if len(starts) < limit:
        seen = {p.id for p in starts}
        contains = db.scalars(base.where(Product.normalized_name.contains(q)).order_by(Product.name).limit(limit))
        starts += [p for p in contains if p.id not in seen][: limit - len(starts)]
    return starts


# ---------------------------------------------------------------- serialización

def _image(key: str | None, url: str | None, source: str) -> dict | None:
    if key:
        storage = get_storage()
        if storage is None:
            return None
        return {"url": storage.presign_get(key), "key": key, "source": source}
    if url:
        return {"url": url, "key": url, "source": source}
    return None


def product_image(product: Product | None) -> dict | None:
    if product is None:
        return None
    return _image(product.image_key, product.image_url, "product")


def item_payload(item: ChecklistItem) -> dict:
    """Datos del elemento con su foto: la propia, o si no la del producto."""
    return {
        "id": item.id,
        "text": item.text,
        "quantity": item.quantity,
        "section": item.section,
        "done": item.done,
        "done_by": item.done_by,
        "product_id": item.product_id,
        "image": _image(item.image_key, None, "item") or product_image(item.product),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def product_payload(product: Product) -> dict:
    return {"id": product.id, "name": product.name, "image": product_image(product)}


# ---------------------------------------------------------------- fotos subidas

def upload_prefix(owner_id: str) -> str:
    return f"owners/{owner_id}/"


def owner_usage(db: Session, owner_id: str) -> int:
    """Bytes de fotos del catálogo y de los elementos de las listas de este dueño."""
    products = db.scalar(
        select(func.coalesce(func.sum(Product.image_size), 0)).where(Product.owner_id == owner_id)
    )
    items = db.scalar(
        select(func.coalesce(func.sum(ChecklistItem.image_size), 0))
        .join(Checklist, ChecklistItem.list_id == Checklist.id)
        .where(Checklist.owner_id == owner_id)
    )
    return int(products) + int(items)


def verify_upload(db: Session, owner_id: str, key: str) -> int:
    """Comprueba que la foto subida exista, sea de este catálogo, sea imagen y respete los límites.

    Devuelve su tamaño en bytes. Si no cumple, la borra y responde 400.
    """
    settings = get_settings()
    storage = require_storage()
    if not key.startswith(upload_prefix(owner_id)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La foto no corresponde a esta lista")
    info = storage.head(key)
    if info is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La foto no se terminó de subir. Intenta de nuevo.")
    if not info.content_type.startswith("image/") or info.size > settings.max_image_bytes:
        storage.delete(key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La foto debe ser una imagen de máximo 2 MB")
    if owner_usage(db, owner_id) + info.size > settings.max_storage_bytes_per_owner:
        storage.delete(key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Se llenó el espacio para fotos de este catálogo")
    return info.size


def delete_object(key: str | None) -> None:
    if key:
        storage = get_storage()
        if storage is not None:
            storage.delete(key)
