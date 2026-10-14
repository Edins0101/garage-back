"""Envío de correos. El proveedor se elige con EMAIL_PROVIDER (ver docs/DEPLOY.md)."""

import logging
from dataclasses import dataclass, field

import requests
from fastapi import HTTPException, status

from app.config import get_settings

log = logging.getLogger("garaje.email")


@dataclass
class Email:
    to: str
    subject: str
    text: str
    html: str


@dataclass
class ConsoleSender:
    """Desarrollo y tests: no envía nada; escribe el correo en el log y lo guarda en memoria."""

    outbox: list[Email] = field(default_factory=list)

    def send(self, email: Email) -> None:
        self.outbox.append(email)
        log.warning("CORREO (modo consola) para %s | %s", email.to, email.subject)


class BrevoSender:
    """Envía por la API HTTP transaccional de Brevo."""

    URL = "https://api.brevo.com/v3/smtp/email"

    def send(self, email: Email) -> None:
        settings = get_settings()
        payload = {
            "sender": {"name": settings.email_from_name, "email": settings.email_from},
            "to": [{"email": email.to}],
            "subject": email.subject,
            "textContent": email.text,
            "htmlContent": email.html,
        }
        try:
            response = requests.post(
                self.URL,
                json=payload,
                headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
                timeout=10,
            )
        except requests.RequestException:
            log.exception("Brevo no respondió")
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No se pudo enviar el correo. Intenta de nuevo.")
        if response.status_code >= 300:
            log.error("Brevo rechazó el correo: %s %s", response.status_code, response.text[:300])
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No se pudo enviar el correo. Intenta de nuevo.")


_console = ConsoleSender()


def get_sender():
    settings = get_settings()
    if settings.email_provider == "brevo" and settings.brevo_api_key and settings.email_from:
        return BrevoSender()
    return _console


def code_email(to: str, code: str, purpose: str, minutes: int) -> Email:
    action = "crear tu cuenta" if purpose == "register" else "cambiar tu contraseña"
    subject = f"{code} es tu código de Garaje"
    text = (
        f"Tu código para {action} en Garaje es: {code}\n\n"
        f"Vence en {minutes} minutos. Si no lo pediste, ignora este correo."
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:420px;margin:auto;padding:24px;
                background:#120A2B;color:#ffffff;border-radius:16px">
      <p style="letter-spacing:4px;color:#C7BFF0;margin:0">GARAJE</p>
      <h2 style="margin:8px 0 16px">Tu código para {action}</h2>
      <p style="font-size:36px;font-weight:800;letter-spacing:10px;background:#ffffff;color:#6A4BE0;
                text-align:center;border-radius:12px;padding:16px;margin:0">{code}</p>
      <p style="color:#C7BFF0;font-size:13px;margin-top:16px">
        Vence en {minutes} minutos. Si no lo pediste, ignora este correo.</p>
    </div>"""
    return Email(to=to, subject=subject, text=text, html=html)
