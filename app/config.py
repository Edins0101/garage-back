from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída de variables de entorno (o del archivo .env en desarrollo)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./garaje.db"
    jwt_secret: str = "dev-secret-cambiar"
    jwt_days: int = 30
    allow_dev_login: bool = False
    google_client_id: str = ""
    invite_days: int = 7

    # Códigos de verificación (OTP) por correo
    require_email_verification: bool = True
    code_ttl_minutes: int = 10
    code_max_attempts: int = 5
    code_resend_seconds: int = 60
    code_max_per_hour: int = 5

    # Envío de correos: "console" (el código sale en los logs) o "brevo" (API HTTP).
    # Render Free bloquea SMTP, por eso se usa una API HTTP.
    email_provider: str = "console"
    brevo_api_key: str = ""
    email_from: str = ""
    email_from_name: str = "Garaje"
    #: Base de los enlaces de invitación que se comparten.
    invite_url_base: str = "garajeapp://join/"

    @property
    def sqlalchemy_url(self) -> str:
        """Normaliza la URL de Render/Neon al driver psycopg 3 y exige SSL en hosts remotos."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url.removeprefix("postgres://")
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
            # SSL obligatorio solo para hosts públicos (con dominio). Los internos de Render
            # (dpg-xxx-a), "localhost" y el "db" de docker compose no llevan punto.
            host = url.split("@", 1)[-1].split("/", 1)[0].split(":", 1)[0]
            is_public = "." in host and host != "127.0.0.1"
            if "sslmode=" not in url and is_public:
                url += ("&" if "?" in url else "?") + "sslmode=require"
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
