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


class MemberOut(ApiModel):
    email: str
    name: str | None = None
    user_id: str | None = None
    role: Role
    status: Status
    invited_at: dt.datetime


class ChecklistOut(ApiModel):
    id: str
    title: str
    kind: Kind
    owner_id: str
    items: list[ItemOut]
    shared_with: list[MemberOut] = Field(validation_alias="members")
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
    list_id: str
    expires_at: dt.datetime


class JoinIn(ApiModel):
    code: str = Field(min_length=4, max_length=12)
