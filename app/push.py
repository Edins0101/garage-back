"""Notificaciones push con Firebase Cloud Messaging (API HTTP v1).

Se envían mensajes solo de datos: la app arma la notificación ella misma (también con la app
abierta) y al tocarla abre la lista. Ver garaje-android/docs/NOTIFICACIONES.md.
"""

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache

import requests
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Checklist, Device, User

log = logging.getLogger("garaje.push")

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


@dataclass
class Push:
    title: str
    body: str
    #: Datos para la app (todos los valores deben ser texto).
    data: dict[str, str] = field(default_factory=dict)
    #: Notificaciones con la misma etiqueta se reemplazan en el teléfono (una por lista).
    tag: str | None = None


@dataclass
class ConsolePushSender:
    """Desarrollo y tests: no envía nada, lo deja en el log y en memoria."""

    sent: list[tuple[str, Push]] = field(default_factory=list)

    def send(self, token: str, push: Push) -> bool:
        self.sent.append((token, push))
        log.warning("PUSH (modo consola) a %s…: %s | %s", token[:12], push.title, push.body)
        return True


class FcmSender:
    def __init__(self) -> None:
        from google.oauth2 import service_account

        info = json.loads(get_settings().firebase_service_account)
        self.project_id = info["project_id"]
        self.credentials = service_account.Credentials.from_service_account_info(info, scopes=[_SCOPE])

    def _token(self) -> str:
        from google.auth.transport.requests import Request

        if not self.credentials.valid:
            self.credentials.refresh(Request())
        return self.credentials.token

    def send(self, token: str, push: Push) -> bool:
        """Envía el mensaje. Devuelve False si el token ya no sirve (app desinstalada, etc.)."""
        message = {
            "token": token,
            "data": {"title": push.title, "body": push.body, **push.data, **({"tag": push.tag} if push.tag else {})},
            "android": {"priority": "HIGH"},
        }
        try:
            response = requests.post(
                f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send",
                json={"message": message},
                headers={"Authorization": f"Bearer {self._token()}"},
                timeout=10,
            )
        except requests.RequestException:
            log.exception("FCM no respondió")
            return True
        if response.status_code == 200:
            return True
        body = response.text[:300]
        if response.status_code == 404 or "UNREGISTERED" in body or ("INVALID_ARGUMENT" in body and "token" in body):
            return False
        log.error("FCM rechazó el mensaje: %s %s", response.status_code, body)
        return True


_console = ConsolePushSender()


@lru_cache
def _fcm() -> FcmSender:
    return FcmSender()


def get_push_sender():
    settings = get_settings()
    if settings.push_provider == "fcm" and settings.firebase_service_account:
        return _fcm()
    return _console


def recipients(db: Session, checklist: Checklist, exclude_user_id: str) -> list[str]:
    """Usuarios que deben enterarse de un cambio en la lista (o sección): dueño y miembros aceptados, menos quien lo hizo."""
    ids = {checklist.owner_id} | {m.user_id for m in checklist.members if m.user_id and m.status == "accepted"}
    ids.discard(exclude_user_id)
    return sorted(ids)


def device_tokens(db: Session, user_ids: list[str]) -> list[str]:
    if not user_ids:
        return []
    return list(db.scalars(select(Device.token).where(Device.user_id.in_(user_ids))))


def send_push(tokens: list[str], push: Push) -> None:
    """Envía la notificación a esos teléfonos. Corre en segundo plano (BackgroundTasks), así
    quien hizo el cambio no espera. Los tokens que ya no sirven se borran."""
    if not tokens:
        return
    try:
        sender = get_push_sender()
        dead = [t for t in tokens if not sender.send(t, push)]
        if dead:
            db = SessionLocal()
            try:
                db.execute(delete(Device).where(Device.token.in_(dead)))
                db.commit()
            finally:
                db.close()
    except Exception:
        log.exception("No se pudieron enviar las notificaciones")


def item_added_push(actor: User, checklist: Checklist, item_text: str) -> Push:
    return Push(
        title=checklist.title,
        body=f"{actor.name} agregó «{item_text}»",
        data={"type": "item_added", "listId": checklist.id},
        tag=f"list-{checklist.id}",
    )


def member_joined_push(actor: User, checklist: Checklist) -> Push:
    return Push(
        title=checklist.title,
        body=f"{actor.name} se unió a la lista",
        data={"type": "member_joined", "listId": checklist.id},
        tag=f"list-{checklist.id}-members",
    )


def _space_title(reminder) -> str:
    from app.reminders import KIND_LABELS

    return KIND_LABELS.get(reminder.space.kind, "Recordatorios")


def reminder_added_push(actor: User, reminder) -> Push:
    return Push(
        title=_space_title(reminder),
        body=f"{actor.name} agregó «{reminder.title}»",
        data={"type": "reminder_added", "kind": reminder.space.kind, "reminderId": reminder.id},
        tag=f"reminder-{reminder.id}",
    )


def reminder_done_push(actor: User, reminder) -> Push:
    verb = "como pagado" if reminder.space.kind == "payments" else "como hecho"
    return Push(
        title=_space_title(reminder),
        body=f"{actor.name} marcó «{reminder.title}» {verb}",
        data={"type": "reminder_done", "kind": reminder.space.kind, "reminderId": reminder.id},
        tag=f"reminder-{reminder.id}",
    )
