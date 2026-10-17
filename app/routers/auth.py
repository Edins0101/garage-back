from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth import CurrentUser, Db, create_token, upsert_user, verify_google_token
from app.config import get_settings
from app.models import User
from app.otp import consume_code, issue_code
from app.passwords import DUMMY_HASH, hash_password, verify_password
from app.schemas import (
    CodeRequestIn,
    DevLoginIn,
    GoogleLoginIn,
    LoginIn,
    MessageOut,
    PreferencesIn,
    PreferencesOut,
    RegisterIn,
    ResetPasswordIn,
    TokenOut,
    UserOut,
)

router = APIRouter(tags=["auth"])


def _session(user: User) -> TokenOut:
    return TokenOut(token=create_token(user), user=UserOut.model_validate(user))


def _ensure_can_register(db, email: str) -> None:
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None and existing.password_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese correo. Inicia sesión.")
    if existing is not None and existing.google_sub:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese correo ya entra con Google.")


@router.post("/auth/codes", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
def request_code(body: CodeRequestIn, db: Db):
    """Envía un código de 6 dígitos al correo para crear la cuenta o recuperar la contraseña."""
    email = str(body.email).lower()
    if body.purpose == "register":
        _ensure_can_register(db, email)
        issue_code(db, email, "register")
        return MessageOut(message="Te enviamos un código a tu correo")

    # Recuperación: la respuesta es la misma exista o no la cuenta (no revela qué correos están registrados).
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.password_hash:
        issue_code(db, email, "reset")
    return MessageOut(message="Si el correo tiene una cuenta, te enviamos un código")


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Db):
    """Crea una cuenta con correo y contraseña (verificando el código del correo) e inicia la sesión."""
    email = str(body.email).lower()
    _ensure_can_register(db, email)
    if get_settings().require_email_verification:
        if not body.code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Falta el código que enviamos a tu correo")
        consume_code(db, email, "register", body.code)
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


@router.post("/auth/password/reset", response_model=TokenOut)
def reset_password(body: ResetPasswordIn, db: Db):
    """Cambia la contraseña con el código enviado al correo e inicia la sesión."""
    email = str(body.email).lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.password_hash:
        # Mismo mensaje que un código inválido: no revela si la cuenta existe.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El código no es válido. Pide uno nuevo.")
    consume_code(db, email, "reset", body.code)
    user.password_hash = hash_password(body.password)
    db.commit()
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


def _preferences(user: User) -> PreferencesOut:
    if not user.preferences:
        return PreferencesOut()
    try:
        return PreferencesOut.model_validate_json(user.preferences)
    except ValueError:
        return PreferencesOut()


@router.get("/me/preferences", response_model=PreferencesOut)
def get_preferences(user: CurrentUser):
    """Inicio y color guardados en la cuenta (vacío si nunca se guardaron)."""
    return _preferences(user)


@router.put("/me/preferences", response_model=PreferencesOut)
def save_preferences(body: PreferencesIn, user: CurrentUser, db: Db):
    current = _preferences(user)
    merged = PreferencesOut(
        home=body.home if body.home is not None else current.home,
        accent=body.accent if body.accent is not None else current.accent,
    )
    user.preferences = merged.model_dump_json(by_alias=True)
    db.commit()
    return merged
