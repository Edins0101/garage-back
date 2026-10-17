"""¿Está libre?: equipos compartidos de la casa (lavadora, secadora, baño, carro…).

Cada equipo está libre u ocupado por alguien. Al ocuparlo o liberarlo se avisa al resto (push),
según lo que cada persona eligió (todo, solo cuando se libere o nada). Si nadie lo libera, se
libera solo: [GRACE] después de la hora estimada o [MAX_BUSY] después si no se dijo cuánto dura.
Se comparte con grupos (ver routers/groups.py); "editor" puede ocuparlo y liberarlo, "viewer" solo ve.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import or_, select

from app.auth import CurrentUser, Db
from app.config import get_settings
from app.models import Appliance, ApplianceNotify, ApplianceUse, GroupShare, User, as_utc, utcnow
from app.permissions import Access, access_level, shared_by_groups
from app.push import Push, device_tokens, send_push
from app.schemas import (
    ApplianceIn,
    ApplianceNotifyIn,
    ApplianceOut,
    AppliancePatchIn,
    ApplianceStartIn,
    ApplianceUseOut,
)

router = APIRouter(tags=["¿está libre?"])

#: Margen después de la hora estimada antes de liberarlo solo.
GRACE = dt.timedelta(minutes=30)
#: Sin hora estimada, se libera solo pasado este tiempo.
MAX_BUSY = dt.timedelta(hours=12)
HISTORY_LIMIT = 30


# ---------------------------------------------------------------- reglas

def _get(db, appliance_id: str, user: User, required: Access = Access.VIEWER) -> Appliance:
    appliance = db.get(Appliance, appliance_id)
    level = access_level(appliance, user) if appliance else Access.NONE
    if level == Access.NONE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El equipo no existe")
    if level < required:
        message = {
            Access.EDITOR: "Solo puedes ver este equipo, no usarlo",
            Access.OWNER: "Solo quien lo creó puede hacer esto",
        }[required]
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)
    appliance.my_access = level
    return appliance


def _release_due(appliance: Appliance) -> dt.datetime | None:
    """Cuándo se libera solo (None si está libre)."""
    if appliance.busy_since is None:
        return None
    if appliance.expected_end is not None:
        return as_utc(appliance.expected_end) + GRACE
    return as_utc(appliance.busy_since) + MAX_BUSY


def _free(appliance: Appliance, ended_by: User | None, auto: bool = False) -> None:
    now = utcnow()
    use = next((u for u in appliance.uses if u.ended_at is None), None)
    if use is not None:
        use.ended_at = now
        use.ended_by_name = ended_by.name if ended_by else None
        use.auto = auto
    appliance.busy_by_id = None
    appliance.busy_since = None
    appliance.expected_end = None


def _expire(db, appliance: Appliance, background: BackgroundTasks | None) -> None:
    """Libera el equipo si ya pasó su hora (sin tareas programadas: se revisa al consultarlo)."""
    due = _release_due(appliance)
    if due is None or utcnow() < due:
        return
    _free(appliance, None, auto=True)
    db.commit()
    if background is not None:
        _notify(db, background, appliance, actor_id=None, freed=True,
                push=_push(appliance, f"{appliance.name} se liberó solo: nadie lo había liberado"))


def _modes(db, appliance: Appliance) -> dict[str, str]:
    rows = db.scalars(select(ApplianceNotify).where(ApplianceNotify.appliance_id == appliance.id))
    return {row.user_id: row.mode for row in rows}


def _audience(appliance: Appliance) -> set[str]:
    ids = {appliance.owner_id}
    for share in appliance.group_shares:
        ids |= share.group.user_ids
    return ids


def _notify(db, background: BackgroundTasks, appliance: Appliance, actor_id: str | None, freed: bool, push: Push) -> None:
    """Avisa a todos menos a quien lo hizo, según lo que eligió cada uno."""
    modes = _modes(db, appliance)
    ids = [
        uid for uid in _audience(appliance)
        if uid != actor_id and (modes.get(uid, "all") == "all" or (freed and modes.get(uid) == "free"))
    ]
    tokens = device_tokens(db, sorted(ids))
    if tokens:
        background.add_task(send_push, tokens, push)


def _push(appliance: Appliance, body: str) -> Push:
    return Push(
        title=appliance.name,
        body=body,
        data={"type": "appliance", "applianceId": appliance.id},
        tag=f"appliance-{appliance.id}",
    )


def _clock(value: dt.datetime) -> str:
    """"3:55 p. m." en la hora de la casa."""
    local = as_utc(value).astimezone(ZoneInfo(get_settings().app_timezone))
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'a. m.' if local.hour < 12 else 'p. m.'}"


def _out(db, appliance: Appliance, user: User, modes: dict[str, str] | None = None) -> ApplianceOut:
    if appliance.my_access is None:
        appliance.my_access = access_level(appliance, user)
    mode = (modes if modes is not None else _modes(db, appliance)).get(user.id, "all")
    return ApplianceOut(
        id=appliance.id,
        name=appliance.name,
        icon=appliance.icon,
        default_minutes=appliance.default_minutes,
        owner_id=appliance.owner_id,
        owner_name=appliance.owner.name,
        role=appliance.my_role,
        busy=appliance.busy_since is not None,
        busy_by_id=appliance.busy_by_id,
        busy_by_name=appliance.busy_by.name if appliance.busy_by else None,
        busy_since=appliance.busy_since,
        expected_end=appliance.expected_end,
        notify=mode,
        groups=appliance.group_shares,
    )


# ---------------------------------------------------------------- rutas

@router.get("/appliances", response_model=list[ApplianceOut])
def list_appliances(user: CurrentUser, db: Db, background: BackgroundTasks):
    """Mis equipos y los de mis grupos (primero los míos)."""
    group_ids = shared_by_groups(GroupShare.appliance_id, user)
    query = select(Appliance).where(or_(Appliance.owner_id == user.id, Appliance.id.in_(group_ids)))
    appliances = sorted(db.scalars(query).all(), key=lambda a: (a.owner_id != user.id, a.created_at))
    for appliance in appliances:
        _expire(db, appliance, background)
    return [_out(db, a, user) for a in appliances]


@router.post("/appliances", response_model=ApplianceOut, status_code=status.HTTP_201_CREATED)
def create_appliance(body: ApplianceIn, user: CurrentUser, db: Db):
    appliance = Appliance(owner_id=user.id, name=body.name.strip(), icon=body.icon, default_minutes=body.default_minutes)
    db.add(appliance)
    db.commit()
    db.refresh(appliance)
    return _out(db, appliance, user)


@router.get("/appliances/{appliance_id}", response_model=ApplianceOut)
def get_appliance(appliance_id: str, user: CurrentUser, db: Db, background: BackgroundTasks):
    appliance = _get(db, appliance_id, user)
    _expire(db, appliance, background)
    return _out(db, appliance, user)


@router.patch("/appliances/{appliance_id}", response_model=ApplianceOut)
def update_appliance(appliance_id: str, body: AppliancePatchIn, user: CurrentUser, db: Db):
    appliance = _get(db, appliance_id, user, Access.OWNER)
    if body.name is not None:
        appliance.name = body.name.strip()
    if body.icon is not None:
        appliance.icon = body.icon
    if "default_minutes" in body.model_fields_set:
        appliance.default_minutes = body.default_minutes
    db.commit()
    db.refresh(appliance)
    return _out(db, appliance, user)


@router.delete("/appliances/{appliance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_appliance(appliance_id: str, user: CurrentUser, db: Db):
    db.delete(_get(db, appliance_id, user, Access.OWNER))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/appliances/{appliance_id}/start", response_model=ApplianceOut)
def start_using(appliance_id: str, body: ApplianceStartIn, user: CurrentUser, db: Db, background: BackgroundTasks):
    """"La estoy usando". 409 si otra persona lo tiene ocupado."""
    appliance = _get(db, appliance_id, user, Access.EDITOR)
    _expire(db, appliance, background)
    if appliance.busy_since is not None and appliance.busy_by_id != user.id:
        who = appliance.busy_by.name if appliance.busy_by else "Alguien"
        raise HTTPException(status.HTTP_409_CONFLICT, f"{who} lo está usando")
    now = utcnow()
    minutes = body.minutes or appliance.default_minutes
    if appliance.busy_since is None:
        appliance.busy_since = now
        appliance.uses.insert(0, ApplianceUse(user_id=user.id, user_name=user.name, started_at=now))
    # Si ya era mío, solo cambia la hora estimada.
    appliance.busy_by_id = user.id
    appliance.expected_end = now + dt.timedelta(minutes=minutes) if minutes else None
    db.commit()
    db.refresh(appliance)
    until = f" · libre aprox. a las {_clock(appliance.expected_end)}" if appliance.expected_end else ""
    _notify(db, background, appliance, user.id, freed=False,
            push=_push(appliance, f"{user.name} empezó a usar {appliance.name}{until}"))
    return _out(db, appliance, user)


@router.post("/appliances/{appliance_id}/finish", response_model=ApplianceOut)
def finish_using(appliance_id: str, user: CurrentUser, db: Db, background: BackgroundTasks):
    """"Ya la liberé". Cualquiera que pueda usarlo lo libera (por si alguien se olvidó)."""
    appliance = _get(db, appliance_id, user, Access.EDITOR)
    if appliance.busy_since is None:
        return _out(db, appliance, user)
    previous = appliance.busy_by
    _free(appliance, user)
    db.commit()
    db.refresh(appliance)
    body = (
        f"{user.name} liberó {appliance.name}: ya está libre"
        if previous is None or previous.id == user.id
        else f"{user.name} liberó {appliance.name} (lo usaba {previous.name}): ya está libre"
    )
    _notify(db, background, appliance, user.id, freed=True, push=_push(appliance, body))
    return _out(db, appliance, user)


@router.put("/appliances/{appliance_id}/notify", response_model=ApplianceOut)
def set_notify(appliance_id: str, body: ApplianceNotifyIn, user: CurrentUser, db: Db):
    """Mis avisos de este equipo: all, free (solo cuando se libere) o none."""
    appliance = _get(db, appliance_id, user)
    row = db.scalar(
        select(ApplianceNotify).where(ApplianceNotify.appliance_id == appliance.id, ApplianceNotify.user_id == user.id)
    )
    if row is None:
        db.add(ApplianceNotify(appliance_id=appliance.id, user_id=user.id, mode=body.mode))
    else:
        row.mode = body.mode
    db.commit()
    return _out(db, appliance, user)


@router.get("/appliances/{appliance_id}/history", response_model=list[ApplianceUseOut])
def history(appliance_id: str, user: CurrentUser, db: Db, background: BackgroundTasks):
    """Los últimos usos, el más reciente primero."""
    appliance = _get(db, appliance_id, user)
    _expire(db, appliance, background)
    return appliance.uses[:HISTORY_LIMIT]
