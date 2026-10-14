"""Sesiones con JWT propio. El login real es con Google; /auth/dev existe solo para desarrollo."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ListMember, User

_bearer = HTTPBearer(auto_error=False)


def create_token(user: User) -> str:
    settings = get_settings()
    payload = {
        "sub": user.id,
        "email": user.email,
        "exp": datetime.now(UTC) + timedelta(days=settings.jwt_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def upsert_user(db: Session, email: str, name: str, google_sub: str | None = None) -> User:
    """Crea o actualiza al usuario y le vincula las invitaciones pendientes hechas a su correo."""
    email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name.strip() or email.split("@")[0], google_sub=google_sub)
        db.add(user)
    else:
        if google_sub and not user.google_sub:
            user.google_sub = google_sub
        if name.strip():
            user.name = name.strip()
    db.flush()

    # Quien fue invitado por correo antes de registrarse obtiene acceso al iniciar sesión.
    pending = db.scalars(select(ListMember).where(ListMember.email == email, ListMember.user_id.is_(None)))
    for member in pending:
        member.user_id = user.id
        member.status = "accepted"
        member.name = member.name or user.name
    db.commit()
    return user


def verify_google_token(id_token_value: str) -> dict:
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "El login con Google no está configurado")
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        info = id_token.verify_oauth2_token(id_token_value, google_requests.Request(), settings.google_client_id)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de Google inválido")
    if not info.get("email_verified"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "El correo de Google no está verificado")
    return info


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inicia sesión para continuar")
    try:
        payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o vencida")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario no encontrado")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
Db = Annotated[Session, Depends(get_db)]
