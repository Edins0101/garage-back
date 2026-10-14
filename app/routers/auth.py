from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth import CurrentUser, Db, create_token, upsert_user, verify_google_token
from app.config import get_settings
from app.models import User
from app.passwords import DUMMY_HASH, hash_password, verify_password
from app.schemas import DevLoginIn, GoogleLoginIn, LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(tags=["auth"])


def _session(user: User) -> TokenOut:
    return TokenOut(token=create_token(user), user=UserOut.model_validate(user))


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Db):
    """Crea una cuenta con correo y contraseña e inicia la sesión."""
    email = str(body.email).lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None and existing.password_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese correo. Inicia sesión.")
    if existing is not None and existing.google_sub:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese correo ya entra con Google.")
    user = upsert_user(db, email, body.name)
    user.password_hash = hash_password(body.password)
    db.commit()
    return _session(user)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Db):
    """Inicia sesión con correo y contraseña."""
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    # Siempre se calcula un hash: así no se puede adivinar qué correos existen por el tiempo de respuesta.
    valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not user.password_hash or not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos")
    return _session(user)


@router.post("/auth/google", response_model=TokenOut)
def login_google(body: GoogleLoginIn, db: Db):
    """Recibe el ID token de "Iniciar sesión con Google" y entrega la sesión de la API."""
    info = verify_google_token(body.id_token)
    user = upsert_user(db, info["email"], info.get("name", ""), google_sub=info["sub"])
    return _session(user)


@router.post("/auth/dev", response_model=TokenOut)
def login_dev(body: DevLoginIn, db: Db):
    """Login sin Google para desarrollo. Deshabilitado salvo ALLOW_DEV_LOGIN=true."""
    if not get_settings().allow_dev_login:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No disponible")
    user = upsert_user(db, body.email, body.name)
    return _session(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
