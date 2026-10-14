"""Tablas de la base de datos (SQLAlchemy 2)."""

import uuid
import datetime as dt
from datetime import UTC, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite devuelve fechas sin zona horaria; las tratamos como UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    #: Hash scrypt de la contraseña (ver app/passwords.py). Vacío si entra solo con Google.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GarageDay(Timestamps, Base):
    """Un día en que el carro del usuario está en el garaje (cada usuario tiene su calendario)."""

    __tablename__ = "garage_days"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class Checklist(Timestamps, Base):
    __tablename__ = "checklists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # shopping | todo
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    items: Mapped[list["ChecklistItem"]] = relationship(
        back_populates="checklist",
        cascade="all, delete-orphan",
        order_by="ChecklistItem.created_at",
    )
    members: Mapped[list["ListMember"]] = relationship(
        back_populates="checklist",
        cascade="all, delete-orphan",
        order_by="ListMember.invited_at",
    )


class ChecklistItem(Timestamps, Base):
    __tablename__ = "checklist_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    list_id: Mapped[str] = mapped_column(ForeignKey("checklists.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[str | None] = mapped_column(String(60))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_by: Mapped[str | None] = mapped_column(String(36))

    checklist: Mapped[Checklist] = relationship(back_populates="items")


class ListMember(Base):
    """Persona con acceso a una lista. Se identifica por correo; user_id se llena al aceptar."""

    __tablename__ = "list_members"
    __table_args__ = (UniqueConstraint("list_id", "email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    list_id: Mapped[str] = mapped_column(ForeignKey("checklists.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # editor | viewer
    status: Mapped[str] = mapped_column(String(16))  # pending | accepted
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    checklist: Mapped[Checklist] = relationship(back_populates="members")


class Invite(Base):
    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    list_id: Mapped[str] = mapped_column(ForeignKey("checklists.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
