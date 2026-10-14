# Despliegue y operación

## Infraestructura actual

| Pieza | Dónde | Notas |
|---|---|---|
| PostgreSQL 18 | Render: base `garaje_app`, región Oregon | **Si es el plan Free, vence 30 días después de crearse** y luego Render la borra. Migrar antes a Neon o pasar a un plan pago. |
| API | Render Web Service (Docker, plan Free) | Se duerme tras unos 15 minutos sin uso; la primera petición después tarda cerca de 1 minuto. |
| Código | GitHub: [Edins0101/garage-back](https://github.com/Edins0101/garage-back) (app: [Edins0101/garage-app](https://github.com/Edins0101/garage-app)) | Render despliega solo en cada push a `main`. |

## Primer despliegue en Render

1. El código ya está en GitHub (`Edins0101/garage-back`, sin `.env`).
2. En Render: **New → Blueprint**, elige el repo. Lee `render.yaml` y crea el servicio `garaje-api`.
3. Completa las variables que pide:
   - `DATABASE_URL`: la **Internal Database URL** de la base (host `dpg-…-a`, sin dominio). Es más rápida y no sale a internet.
   - `GOOGLE_CLIENT_ID`: dejar vacío hasta configurar el login con Google.
   - `JWT_SECRET` lo genera Render solo.
4. Al arrancar, el contenedor corre `alembic upgrade head` y luego la API.
5. Prueba: `https://garaje-api.onrender.com/health` → `{"status":"ok"}`. El nombre exacto lo da Render.
6. En la app (`garaje-android/app/build.gradle.kts`): `API_URL = "https://<servicio>.onrender.com/api"` y `USE_FAKES = false`.

## Desarrollo local

- **Contra la base de Render**: `.env` con la External Database URL y luego `uvicorn app.main:app --reload`.
  Ojo: escribes en la misma base que producción.
- **Totalmente offline**: `docker compose up --build` (API + Postgres 18 en Docker, con ALLOW_DEV_LOGIN activo).
  Requiere Docker Desktop abierto.
- Desde el emulador Android, la PC es `http://10.0.2.2:8000/api`. Para HTTP sin TLS, la app necesita permitir cleartext solo en debug.

## Login

- **Producción**: "Iniciar sesión con Google". La app obtiene un ID token y llama `POST /api/auth/google`.
  Requiere crear en Google Cloud un OAuth Client ID de tipo **Web** (su ID va en `GOOGLE_CLIENT_ID`)
  y otro de tipo **Android** (paquete `com.garaje.app` + huella SHA-1 del keystore).
- **Desarrollo**: `POST /api/auth/dev {email, name}` solo funciona con `ALLOW_DEV_LOGIN=true`.
  **Nunca activarlo en producción.**

## Seguridad y mantenimiento

- **Rotar la contraseña de la base**: se compartió en un chat. En Render: base → Info → Credentials → nueva contraseña. Después actualizar `.env` y la variable `DATABASE_URL` del servicio.
- Si `JWT_SECRET` cambia, todas las sesiones se invalidan y hay que volver a iniciar sesión.
- Respaldos: el plan Free de Render no los incluye. Para un respaldo manual:
  `pg_dump "<External Database URL>" > respaldo.sql`.

## Migrar la base a Neon (cuando venza la de Render)

1. Crear el proyecto en Neon y copiar su connection string.
2. `pg_dump "<URL Render>" | psql "<URL Neon>"`.
3. Cambiar `DATABASE_URL` en Render (servicio) y en `.env`. No hay cambios de código.
