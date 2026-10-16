from fastapi import APIRouter, Response, status
from sqlalchemy import delete, select

from app.auth import CurrentUser, Db
from app.models import Device, utcnow
from app.schemas import DeviceIn

router = APIRouter(prefix="/devices", tags=["notificaciones"])


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def register_device(body: DeviceIn, user: CurrentUser, db: Db):
    """Registra (o reasigna) el token de notificaciones de este teléfono al usuario actual."""
    device = db.scalar(select(Device).where(Device.token == body.token))
    if device is None:
        db.add(Device(user_id=user.id, token=body.token, platform=body.platform))
    else:
        # Si otra persona inició sesión antes en este teléfono, el token pasa al usuario actual.
        device.user_id = user.id
        device.last_seen_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
def unregister_device(token: str, user: CurrentUser, db: Db):
    """Al cerrar sesión: este teléfono deja de recibir notificaciones de este usuario."""
    db.execute(delete(Device).where(Device.token == token, Device.user_id == user.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
