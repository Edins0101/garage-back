"""Códigos de un solo uso por correo: emisión con límites y verificación con intentos acotados."""

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.email import ConsoleSender, code_email, get_sender
from app.models import EmailCode, as_utc, utcnow

log = logging.getLogger("garaje.otp")


def _hash(email: str, purpose: str, code: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{purpose}:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_code(db: Session, email: str, purpose: str) -> None:
    """Genera un código nuevo (invalida los anteriores) y lo envía por correo."""
    settings = get_settings()
    now = utcnow()

    last = db.scalar(
        select(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose)
        .order_by(EmailCode.created_at.desc())
    )
    if last is not None:
        wait = settings.code_resend_seconds - (now - as_utc(last.created_at)).total_seconds()
        if wait > 0:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, f"Espera {int(wait) + 1} segundos para pedir otro código"
            )

    sent_last_hour = db.scalar(
        select(func.count())
        .select_from(EmailCode)
        .where(EmailCode.email == email, EmailCode.created_at > now - timedelta(hours=1))
    )
    if sent_last_hour >= settings.code_max_per_hour:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Pediste demasiados códigos. Intenta en una hora.")

    db.execute(
        update(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.used.is_(False))
        .values(used=True)
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        EmailCode(
            email=email,
            purpose=purpose,
            code_hash=_hash(email, purpose, code),
            expires_at=now + timedelta(minutes=settings.code_ttl_minutes),
        )
    )
    db.commit()

    sender = get_sender()
    if isinstance(sender, ConsoleSender):
        # Sin proveedor de correo configurado, el código queda en los logs (Render → Logs).
        log.warning("CÓDIGO %s para %s (%s)", code, email, purpose)
    sender.send(code_email(email, code, purpose, settings.code_ttl_minutes))


def consume_code(db: Session, email: str, purpose: str, code: str) -> None:
    """Valida el código y lo marca como usado. Lanza 400 con un mensaje claro si no sirve."""
    settings = get_settings()
    current = db.scalar(
        select(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.used.is_(False))
        .order_by(EmailCode.created_at.desc())
    )
    if current is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El código no es válido. Pide uno nuevo.")
    if as_utc(current.expires_at) <= utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El código venció. Pide uno nuevo.")
    if current.attempts >= settings.code_max_attempts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Demasiados intentos. Pide un código nuevo.")

    if not hmac.compare_digest(current.code_hash, _hash(email, purpose, code.strip())):
        current.attempts += 1
        db.commit()
        remaining = settings.code_max_attempts - current.attempts
        if remaining <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Demasiados intentos. Pide un código nuevo.")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Código incorrecto. Te quedan {remaining} intentos.")

    current.used = True
    db.commit()
