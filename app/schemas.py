"""Esquemas JSON de la API. Usan camelCase para coincidir con los modelos de la app Android."""

import datetime as dt
from datetime import UTC
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_serializer, model_validator
from pydantic.alias_generators import to_camel

Kind = Literal["shopping", "todo"]

#: Montos en dólares: no negativos, máximo 2 decimales.
Money = Annotated[Decimal, Field(ge=0, le=Decimal("100000"), max_digits=10, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, le=Decimal("100000"), max_digits=10, decimal_places=2)]
Role = Literal["editor", "viewer"]
Status = Literal["pending", "accepted"]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    @field_serializer("*", when_used="json")
    def _utc(self, value):
        # Todos los timestamps salen en UTC con "Z" (Instant.parse en Android lo exige).
        if isinstance(value, dt.datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return value


# ---------------------------------------------------------------- usuarios y auth

class UserOut(ApiModel):
    id: str
    name: str
    email: str


class GoogleLoginIn(ApiModel):
    id_token: str


class CodeRequestIn(ApiModel):
    email: EmailStr
    purpose: Literal["register", "reset"]


class RegisterIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    #: Código de 6 dígitos enviado al correo (obligatorio si REQUIRE_EMAIL_VERIFICATION=true).
    code: str | None = Field(default=None, max_length=12)


class ResetPasswordIn(ApiModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    password: str = Field(min_length=8, max_length=128)


class MessageOut(ApiModel):
    message: str


class LoginIn(ApiModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class DevLoginIn(ApiModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)


class TokenOut(ApiModel):
    token: str
    user: UserOut


# ---------------------------------------------------------------- garaje

class ChargeOut(ApiModel):
    id: str
    description: str
    amount: float
    created_at: dt.datetime


class GarageDayOut(ApiModel):
    date: dt.date
    note: str | None = None
    #: Tarifa de ese día (null si no había tarifa configurada al marcarlo).
    rate: float | None = None
    charges: list[ChargeOut] = []
    created_at: dt.datetime
    updated_at: dt.datetime

    @computed_field
    @property
    def total(self) -> float:
        return round((self.rate or 0) + sum(c.amount for c in self.charges), 2)


class DayIn(ApiModel):
    """Campos opcionales: los que no se envían no cambian."""

    note: str | None = Field(default=None, max_length=500)
    rate: Money | None = None


class ChargeIn(ApiModel):
    description: str = Field(min_length=1, max_length=120)
    amount: PositiveMoney


class GarageSettingsOut(ApiModel):
    daily_rate: float | None = None
    auto_mark: bool = False
    #: "Hoy" según la zona horaria de la app (útil para la UI).
    today: dt.date


class GarageSettingsIn(ApiModel):
    """Campos opcionales: los que no se envían no cambian."""

    daily_rate: Money | None = None
    auto_mark: bool | None = None
    #: Al cambiar la tarifa, aplicarla también a los días ya marcados que no tienen tarifa.
    apply_to_days_without_rate: bool = True


class PaymentIn(ApiModel):
    date: dt.date
    amount: PositiveMoney
    note: str | None = Field(default=None, max_length=200)


class PaymentOut(ApiModel):
    id: str
    date: dt.date
    amount: float
    note: str | None = None
    created_at: dt.datetime


TrackerIcon = Literal["car", "child", "bus", "gym", "work", "pet", "home", "other"]
Direction = Literal["pay", "earn"]


class TrackerIn(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    icon: TrackerIcon = "other"
    direction: Direction = "pay"
    daily_rate: Money | None = None
    auto_mark: bool = False
    list_id: str | None = None


class TrackerPatchIn(ApiModel):
    """Campos opcionales: los que no se envían no cambian."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    icon: TrackerIcon | None = None
    direction: Direction | None = None
    daily_rate: Money | None = None
    auto_mark: bool | None = None
    #: Lista adjunta; null la quita.
    list_id: str | None = None
    #: Al cambiar la tarifa, aplicarla también a los días ya marcados que no tienen tarifa.
    apply_to_days_without_rate: bool = True


class GarageSummaryOut(ApiModel):
    """Cuenta del garaje hasta la fecha `until` (incluida)."""

    until: dt.date
    daily_rate: float | None
    days: int
    days_without_rate: int
    days_total: float
    charges_total: float
    total: float
    paid: float
    pending: float
    #: Último día pagado por completo: hasta esa fecha los días quedan cerrados (no se editan).
    paid_until: dt.date | None = None


# ---------------------------------------------------------------- listas

class ImageOut(ApiModel):
    #: Enlace para mostrar la foto (firmado y temporal si es subida; tal cual si es una URL externa).
    url: str
    #: Identificador estable para la caché de la app (el enlace firmado cambia en cada respuesta).
    key: str
    source: Literal["item", "product"]


class ItemOut(ApiModel):
    id: str
    text: str
    quantity: str | None = None
    done: bool
    done_by: str | None = None
    product_id: str | None = None
    image: ImageOut | None = None
    created_at: dt.datetime
    updated_at: dt.datetime

    @model_validator(mode="before")
    @classmethod
    def _resolve_image(cls, data):
        from app.catalog import item_payload
        from app.models import ChecklistItem

        return item_payload(data) if isinstance(data, ChecklistItem) else data


class ProductOut(ApiModel):
    id: str
    name: str
    image: ImageOut | None = None

    @model_validator(mode="before")
    @classmethod
    def _resolve_image(cls, data):
        from app.catalog import product_payload
        from app.models import Product

        return product_payload(data) if isinstance(data, Product) else data


class UploadIn(ApiModel):
    list_id: str
    content_type: Literal["image/jpeg", "image/webp", "image/png"] = "image/jpeg"


class UploadOut(ApiModel):
    upload_url: str
    key: str
    content_type: str


class ImageIn(ApiModel):
    """Una de las dos: `key` (foto ya subida con /uploads) o `url` (imagen externa https)."""

    key: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2000, pattern=r"^https://")


class DeviceIn(ApiModel):
    token: str = Field(min_length=10, max_length=512)
    platform: Literal["android"] = "android"


class MemberOut(ApiModel):
    email: str
    name: str | None = None
    user_id: str | None = None
    role: Role
    status: Status
    invited_at: dt.datetime


class GroupShareOut(ApiModel):
    """Con qué grupo se compartió algo y con qué permiso."""

    group_id: str
    group_name: str
    role: Role


class ChecklistOut(ApiModel):
    id: str
    title: str
    kind: Kind
    owner_id: str
    items: list[ItemOut]
    shared_with: list[MemberOut] = Field(validation_alias="members")
    groups: list[GroupShareOut] = Field(default=[], validation_alias="group_shares")
    #: Mi permiso sobre la lista (directo o por un grupo).
    role: Literal["owner", "editor", "viewer"] = Field(default="owner", validation_alias="my_role")
    created_at: dt.datetime
    updated_at: dt.datetime


class NewListIn(ApiModel):
    title: str = Field(min_length=1, max_length=120)
    kind: Kind


class TitleIn(ApiModel):
    title: str = Field(min_length=1, max_length=120)


class NewItemIn(ApiModel):
    text: str = Field(min_length=1, max_length=200)
    quantity: str | None = Field(default=None, max_length=60)


class ItemPatchIn(ApiModel):
    text: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: str | None = Field(default=None, max_length=60)
    done: bool | None = None


# ---------------------------------------------------------------- compartir

class InviteIn(ApiModel):
    email: EmailStr
    role: Role


class InviteOut(ApiModel):
    code: str
    url: str
    #: Uno de los tres: la lista, la sección de recordatorios o el contador al que invita.
    list_id: str | None = None
    space_id: str | None = None
    tracker_id: str | None = None
    group_id: str | None = None
    expires_at: dt.datetime


class JoinIn(ApiModel):
    code: str = Field(min_length=4, max_length=12)


class JoinOut(ApiModel):
    """Resultado de POST /join: a qué se unió la persona con el código."""

    type: Literal["list", "space", "tracker", "group"]
    list_id: str | None = None
    space_id: str | None = None
    tracker_id: str | None = None
    group_id: str | None = None
    kind: str | None = None


# ---------------------------------------------------------------- recordatorios

SpaceKind = Literal["payments", "home", "car", "other"]
Unit = Literal["day", "week", "month", "year"]
CountFrom = Literal["due", "done"]
#: Anticipación del aviso con hora: hasta una semana antes.
AlertMinutes = Annotated[int, Field(ge=0, le=10_080)]


class SpaceOut(ApiModel):
    id: str
    kind: SpaceKind
    owner_id: str
    owner_name: str
    members: list[MemberOut]
    groups: list[GroupShareOut] = []
    #: Mi permiso sobre la sección (directo o por un grupo).
    role: Literal["owner", "editor", "viewer"] = "owner"

    @model_validator(mode="before")
    @classmethod
    def _owner(cls, data):
        from app.models import Space

        if isinstance(data, Space):
            return {
                "id": data.id,
                "kind": data.kind,
                "owner_id": data.owner_id,
                "owner_name": data.owner.name,
                "members": data.members,
                "groups": data.group_shares,
                "role": data.my_role,
            }
        return data


class ReminderLogOut(ApiModel):
    id: str
    due_date: dt.date
    amount: float | None = None
    note: str | None = None
    odometer: int | None = None
    done_by: str | None = None
    done_by_name: str | None = None
    created_at: dt.datetime


class ReminderOut(ApiModel):
    id: str
    space_id: str
    kind: SpaceKind
    title: str
    amount: float | None = None
    every: int | None = None
    unit: Unit | None = None
    next_due: dt.date
    notify_days_before: int
    count_from: CountFrom = "due"
    every_km: int | None = None
    due_time: dt.time | None = None
    alert_minutes: int | None = None
    list_id: str | None = None
    note: str | None = None
    finished: bool
    last_done: ReminderLogOut | None = None
    created_at: dt.datetime
    updated_at: dt.datetime

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data):
        from app.models import Reminder

        if isinstance(data, Reminder):
            fields = {name: getattr(data, name) for name in (
                "id", "space_id", "title", "amount", "every", "unit", "next_due", "notify_days_before",
                "count_from", "every_km", "due_time", "alert_minutes", "list_id", "note", "finished",
                "created_at", "updated_at",
            )}
            return {**fields, "kind": data.space.kind, "last_done": data.logs[0] if data.logs else None}
        return data


def _check_repeat(every: int | None, unit: str | None) -> None:
    if (every is None) != (unit is None):
        raise ValueError("Indica cada cuánto se repite (número y unidad) o ninguno de los dos")


class NewReminderIn(ApiModel):
    kind: SpaceKind
    #: Sección donde se crea; por defecto la propia de ese tipo.
    space_id: str | None = None
    title: str = Field(min_length=1, max_length=120)
    amount: Money | None = None
    every: int | None = Field(default=None, ge=1, le=365)
    unit: Unit | None = None
    next_due: dt.date
    notify_days_before: int = Field(default=2, ge=0, le=60)
    #: Si no se envía: "due" en pagos y "done" en Mi hogar / Mi carro.
    count_from: CountFrom | None = None
    every_km: int | None = Field(default=None, ge=100, le=200_000)
    due_time: dt.time | None = None
    alert_minutes: AlertMinutes | None = None
    list_id: str | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _repeat(self):
        _check_repeat(self.every, self.unit)
        return self


class ReminderPatchIn(ApiModel):
    """Solo cambian los campos enviados; amount, note y la repetición se borran enviando null."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    amount: Money | None = None
    every: int | None = Field(default=None, ge=1, le=365)
    unit: Unit | None = None
    next_due: dt.date | None = None
    notify_days_before: int | None = Field(default=None, ge=0, le=60)
    count_from: CountFrom | None = None
    every_km: int | None = Field(default=None, ge=100, le=200_000)
    due_time: dt.time | None = None
    alert_minutes: AlertMinutes | None = None
    list_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


class DoneIn(ApiModel):
    #: Lo que realmente se pagó (por defecto, el monto estimado).
    amount: Money | None = None
    note: str | None = Field(default=None, max_length=200)
    #: Kilometraje actual (Mi carro).
    odometer: int | None = Field(default=None, ge=0, le=5_000_000)


class TrackerOut(ApiModel):
    """Contador con su configuración y la cuenta hasta hoy (para listarlos sin otra consulta)."""

    id: str
    owner_id: str
    owner_name: str
    #: Mi permiso sobre el contador.
    role: Literal["owner", "editor", "viewer"]
    members: list[MemberOut] = []
    groups: list[GroupShareOut] = []
    name: str
    icon: TrackerIcon
    direction: Direction
    daily_rate: float | None = None
    auto_mark: bool = False
    list_id: str | None = None
    today: dt.date
    summary: GarageSummaryOut
    created_at: dt.datetime


# ---------------------------------------------------------------- grupos

class GroupIn(ApiModel):
    name: str = Field(min_length=1, max_length=80)


class GroupMemberIn(ApiModel):
    email: EmailStr


class GroupMemberOut(ApiModel):
    email: str
    name: str | None = None
    user_id: str | None = None
    status: Status
    invited_at: dt.datetime


class GroupItemOut(ApiModel):
    """Algo compartido con el grupo, para mostrarlo en la pantalla del grupo."""

    type: Literal["list", "space", "tracker"]
    id: str
    title: str
    #: shopping/todo (lista), payments/home/car/other (sección) o el ícono del contador.
    kind: str
    owner_id: str
    owner_name: str
    role: Role


class GroupOut(ApiModel):
    id: str
    name: str
    owner_id: str
    owner_name: str
    #: Mi lugar en el grupo.
    role: Literal["owner", "member"]
    members: list[GroupMemberOut]
    shared: list[GroupItemOut]
    created_at: dt.datetime


class GroupShareIn(ApiModel):
    role: Role = "editor"
