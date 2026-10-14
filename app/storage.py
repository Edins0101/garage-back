"""Almacenamiento de fotos en un bucket privado compatible con S3 (Supabase Storage, R2, B2…)."""

import logging
from dataclasses import dataclass
from functools import lru_cache

from fastapi import HTTPException, status

from app.config import get_settings

log = logging.getLogger("garaje.storage")


@dataclass
class ObjectInfo:
    size: int
    content_type: str


class S3Storage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        settings = get_settings()
        self.bucket = settings.storage_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint,
            region_name=settings.storage_region,
            aws_access_key_id=settings.storage_key_id,
            aws_secret_access_key=settings.storage_secret,
            # Supabase Storage exige direcciones "path-style" (endpoint/bucket/clave).
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presign_put(self, key: str, content_type: str, seconds: int = 600) -> str:
        """Enlace temporal para que la app suba la foto directo al bucket (sin pasar por la API)."""
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=seconds,
        )

    def presign_get(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=get_settings().signed_url_seconds,
        )

    def head(self, key: str) -> ObjectInfo | None:
        from botocore.exceptions import ClientError

        try:
            meta = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return None
        return ObjectInfo(size=meta["ContentLength"], content_type=meta.get("ContentType", ""))

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:  # una foto huérfana no debe romper la operación del usuario
            log.exception("No se pudo borrar %s", key)


@lru_cache
def _s3() -> S3Storage:
    return S3Storage()


def get_storage():
    """El almacenamiento configurado, o None si faltan las variables STORAGE_*."""
    s = get_settings()
    if not (s.storage_endpoint and s.storage_bucket and s.storage_key_id and s.storage_secret):
        return None
    return _s3()


def require_storage():
    storage = get_storage()
    if storage is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Las fotos todavía no están configuradas")
    return storage
