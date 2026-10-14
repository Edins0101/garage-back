from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import engine
from app.routers import auth, garage, lists, sharing

app = FastAPI(
    title="Garaje API",
    version="0.1.0",
    description="Backend de la app Garaje: días del carro en el garaje y listas compartidas.",
)

# Todas las rutas de negocio viven bajo /api (la app usa API_URL=https://…/api).
api = APIRouter(prefix="/api")
for module in (auth, garage, lists, sharing):
    api.include_router(module.router)
app.include_router(api)


# La app espera los errores como {"message": "..."} (ver docs/API.md).
@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse({"message": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:])
    message = f"Dato inválido en '{field}': {first.get('msg', '')}" if field else "Datos inválidos"
    return JSONResponse({"message": message}, status_code=422)


@app.get("/health", tags=["sistema"])
def health():
    """Para el health check de Render y para "despertar" el servicio."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
