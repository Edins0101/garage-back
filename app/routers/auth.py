from fastapi import APIRouter, HTTPException, status

from app.auth import CurrentUser, Db, create_token, upsert_user, verify_google_token
from app.config import get_settings
from app.schemas import DevLoginIn, GoogleLoginIn, TokenOut, UserOut

router = APIRouter(tags=["auth"])


@router.post("/auth/google", response_model=TokenOut)
def login_google(body: GoogleLoginIn, db: Db):
    """Recibe el ID token de "Iniciar sesión con Google" y entrega la sesión de la API."""
    info = verify_google_token(body.id_token)
    user = upsert_user(db, info["email"], info.get("name", ""), google_sub=info["sub"])
    return TokenOut(token=create_token(user), user=UserOut.model_validate(user))


@router.post("/auth/dev", response_model=TokenOut)
def login_dev(body: DevLoginIn, db: Db):
    """Login sin Google para desarrollo. Deshabilitado salvo ALLOW_DEV_LOGIN=true."""
    if not get_settings().allow_dev_login:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No disponible")
    user = upsert_user(db, body.email, body.name)
    return TokenOut(token=create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
