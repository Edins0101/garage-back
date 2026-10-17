# Despliegue y operación

## Infraestructura actual

| Pieza | Dónde | Notas |
|---|---|---|
| PostgreSQL 18 | Render: base `garaje_app`, región Oregon | **Si es el plan Free, vence 30 días después de crearse** y luego Render la borra. Migrar antes a Neon o pasar a un plan pago. |
| API | Render Web Service `arianna-back` (Docker, plan Free): **https://arianna-back.onrender.com** (`/health`, `/docs`) | Se duerme tras unos 15 minutos sin uso; la primera petición después tarda cerca de 1 minuto. El servicio anterior `garage-back-me4r` se borró el 2026-10-17: las versiones de la app anteriores a la v0.8.1 ya no se conectan. |
| Enlaces de invitación | El mismo servicio: `/join/CODIGO` (página) y `/.well-known/assetlinks.json` (App Links) | Si cambia la dirección del servidor hay que actualizar `API_URL`, el intent-filter https del manifest y el deep link de `JoinRoute` en la app, y `INVITE_URL_BASE`. Si cambia la llave de firma, `ANDROID_CERT_SHA256`. |
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

## Variables de entorno en Render

Todas están en [.env.example](../.env.example), con su explicación. En producción revisar siempre:

- `ALLOW_DEV_LOGIN=false` (con `true` cualquiera entra a cualquier cuenta sin contraseña).
- `INVITE_URL_BASE=https://arianna-back.onrender.com/join/`, o borrarla para usar la del código.
- `EMAIL_PROVIDER=brevo` + `BREVO_API_KEY` + `EMAIL_FROM`, y `PUSH_PROVIDER=fcm` + `FIREBASE_SERVICE_ACCOUNT`.

Al crear un servicio nuevo, comprobar desde fuera que `POST /api/auth/dev` responda 404.

## Login

- **Producción**: correo y contraseña (`/auth/register`, `/auth/login`). Debe estar `ALLOW_DEV_LOGIN=false`.
- **Opcional, más adelante**: "Iniciar sesión con Google". La app obtiene un ID token y llama `POST /api/auth/google`.
  Requiere crear en Google Cloud un OAuth Client ID de tipo **Web** (su ID va en `GOOGLE_CLIENT_ID`)
  y otro de tipo **Android** (paquete `com.arianna.app` + huella SHA-1 del keystore).
- **Desarrollo**: `POST /api/auth/dev {email, name}` solo funciona con `ALLOW_DEV_LOGIN=true`.
  **Nunca activarlo en producción.**

## Correos (códigos de verificación)

Render Free **bloquea SMTP** (puertos 25/465/587), así que los correos salen por la API HTTP de **Brevo**.

1. Crear una cuenta gratis en brevo.com.
2. **Senders, domains & dedicated IPs → Senders → Add a sender**: tu correo (puede ser Gmail) y confirmarlo desde el correo que te llega.
3. **SMTP & API → API Keys → Generate a new API key**.
4. En Render (servicio → Environment):
   - `EMAIL_PROVIDER` = `brevo`
   - `BREVO_API_KEY` = la clave del paso 3
   - `EMAIL_FROM` = el correo verificado en el paso 2
   - `EMAIL_FROM_NAME` = `Arianna` (opcional)

Mientras no esté configurado (`EMAIL_PROVIDER=console`), **el código aparece en Render → Logs**
como `CÓDIGO 123456 para correo@... (register)`. Sirve para probar.

Nota: si envías desde un Gmail, algunos correos pueden caer en spam. Con un dominio propio verificado en Brevo mejora la entrega.

## Notificaciones push (Firebase Cloud Messaging)

1. En console.firebase.google.com: crear proyecto → agregar app **Android** con paquete `com.arianna.app` →
   descargar `google-services.json` y ponerlo en `garaje-android/app/` (ya está en .gitignore).
2. **Configuración del proyecto → Cuentas de servicio → Generar nueva clave privada**: descarga un JSON.
3. En Render (Environment):
   - `PUSH_PROVIDER` = `fcm`
   - `FIREBASE_SERVICE_ACCOUNT` = el contenido completo de ese JSON (pegarlo tal cual).

Con `PUSH_PROVIDER=console` las notificaciones solo se escriben en Render → Logs (`PUSH (modo consola)…`).
Se avisa cuando alguien agrega un elemento a una lista compartida o se une a ella; nunca a quien hizo el cambio.

## Seguridad y mantenimiento

- **Rotar la contraseña de la base**: se compartió en un chat. En Render: base → Info → Credentials → nueva contraseña. Después actualizar `.env` y la variable `DATABASE_URL` del servicio.
- Si `JWT_SECRET` cambia, todas las sesiones se invalidan y hay que volver a iniciar sesión.
- Respaldos: el plan Free de Render no los incluye. Para un respaldo manual:
  `pg_dump "<External Database URL>" > respaldo.sql`.

## Migrar la base a Neon (cuando venza la de Render)

1. Crear el proyecto en Neon y copiar su connection string.
2. `pg_dump "<URL Render>" | psql "<URL Neon>"`.
3. Cambiar `DATABASE_URL` en Render (servicio) y en `.env`. No hay cambios de código.
