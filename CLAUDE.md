# Arianna API (backend)

Backend de la app Android `D:\Projects\garaje-android`: **FastAPI + SQLAlchemy 2 + Alembic +
PostgreSQL**. La app se llama **Arianna** (antes Garaje). Gestiona los días del carro en el garaje (por usuario) y las listas
compartidas con permisos.

- Contrato de la API: `garaje-android/docs/API.md` (es la fuente de verdad que comparten la app y este backend)
- Despliegue y operación: [docs/DEPLOY.md](docs/DEPLOY.md)
- Avance del proyecto: `garaje-android/docs/PROGRESS.md`

## Estructura

```
app/
├── main.py          # App, prefijo /api, errores {"message"}, /health
├── config.py        # Settings desde variables de entorno o .env; normaliza la URL de Postgres
├── db.py            # Engine, sesión y Base
├── models.py        # Tablas: users, garage_days, checklists, checklist_items, list_members, invites
├── schemas.py       # JSON en camelCase (igual que los modelos Kotlin); fechas UTC con "Z"
├── auth.py          # JWT propio, login con Google, invitaciones pendientes al iniciar sesión
├── permissions.py   # Acceso a listas: OWNER > EDITOR > VIEWER > NONE (NONE responde 404)
└── routers/         # auth, garage, lists, sharing
alembic/             # Migraciones (la URL sale de DATABASE_URL)
tests/               # pytest sobre SQLite en memoria (nunca tocan la base real)
```

## Comandos (PowerShell o bash, desde esta carpeta)

```bash
.venv/Scripts/python -m pytest -q                              # tests
.venv/Scripts/uvicorn app.main:app --reload --port 8000        # API local (usa la base de .env)
.venv/Scripts/alembic revision --autogenerate -m "descripcion" # nueva migración tras cambiar models.py
.venv/Scripts/alembic upgrade head                             # aplicar migraciones
```

Documentación interactiva con la API corriendo: http://localhost:8000/docs

## Reglas

- **`.env` tiene credenciales reales: nunca subirlo a git** (ya está en `.gitignore`). La plantilla es `.env.example`.
- Todo cambio de endpoint se refleja en `garaje-android/docs/API.md` y en `RemoteRepositories.kt`.
- Los cambios de esquema siempre van por migración de Alembic; nunca se edita la base a mano.
- **Nunca correr `alembic upgrade` contra la base de producción desde local.** Las migraciones las aplica Render al arrancar el contenedor. Si la base queda adelantada respecto del código desplegado, el contenedor falla en bucle con "Can't locate revision" (pasó el 2026-10-14). Probar las migraciones con `docker compose` o SQLite.
- Antes de terminar una tarea: `pytest` en verde y actualizar `garaje-android/docs/PROGRESS.md`.
