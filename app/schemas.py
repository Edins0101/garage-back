"""Esquemas JSON de la API. Usan camelCase para coincidir con los modelos de la app Android."""

import datetime as dt
from datetime import UTC
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer
from pydantic.alias_generators import to_camel

Kind = Literal["shopping", "todo"]
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


class DevLoginIn(ApiModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)


class TokenOut(ApiModel):
    token: str
    user: UserOut


# ---------------------------------------------------------------- garaje

class GarageDayOut(ApiModel):
    date: dt.date
    note: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class NoteIn(ApiModel):
    note: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------- listas

class ItemOut(ApiModel):
    id: str
    text: str
    quantity: str | None = None
    done: bool
    done_by: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


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
