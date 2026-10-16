from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import engine
from app.routers import auth, devices, garage, lists, photos, reminders, sharing

app = FastAPI(
    title="Arianna API",
    version="0.1.0",
    description="Backend de la app Arianna: días del garaje, listas compartidas y pagos.",
)

# Todas las rutas de negocio viven bajo /api (la app usa API_URL=https://…/api).
api = APIRouter(prefix="/api")
for module in (auth, garage, lists, sharing, photos, devices, reminders):
    api.include_router(module.router)
app.include_router(api)


# La app espera los errores como {"message": "..."} (ver docs/API.md).
@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse({"message": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)


_FIELD_NAMES = {"password": "La contraseña", "email": "El correo", "name": "El nombre", "title": "El nombre", "text": "El texto"}


def _validation_message(error: dict) -> str:
    """Convierte el primer error de Pydantic en un mensaje claro en español."""
    field = str(error.get("loc", ["", ""])[-1])
    subject = _FIELD_NAMES.get(field, f"El campo '{field}'")
    ctx = error.get("ctx") or {}
    match error.get("type"):
        case "string_too_short":
            return f"{subject} debe tener al menos {ctx.get('min_length')} caracteres"
        case "string_too_long":
            return f"{subject} puede tener como máximo {ctx.get('max_length')} caracteres"
        case "missing":
            return f"Falta {subject.lower()}"
        case "value_error" if field == "email":
            return "El correo no es válido"
        case _:
            return f"{subject} no es válido"


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errors = exc.errors()
    message = _validation_message(errors[0]) if errors else "Datos inválidos"
    return JSONResponse({"message": message}, status_code=422)


@app.get("/health", tags=["sistema"])
def health():
    """Para el health check de Render y para "despertar" el servicio."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
