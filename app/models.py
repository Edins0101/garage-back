"""Tablas de la base de datos (SQLAlchemy 2)."""

import uuid
import datetime as dt
from datetime import UTC, datetime

from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
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
    #: Tarifa por día del garaje vigente. Se copia a cada día al marcarlo.
    garage_daily_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    #: Si está activo, cada día se marca solo con la tarifa por defecto (ver app/garage.py).
    garage_auto_mark: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: Último día ya rellenado automáticamente: los días que el usuario quite no vuelven a aparecer.
    garage_auto_filled_until: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GarageDay(Timestamps, Base):
    """Un día en que el carro del usuario está en el garaje (cada usuario tiene su calendario)."""

    __tablename__ = "garage_days"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    #: Tarifa de ESTE día (copia de la vigente al marcarlo): cambiar la tarifa no altera el pasado.
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    charges: Mapped[list["GarageCharge"]] = relationship(
        back_populates="day",
        cascade="all, delete-orphan",
        order_by="GarageCharge.created_at",
        lazy="selectin",
    )


class GarageCharge(Base):
    """Cargo extra de un día (lavado, multa, llaves…). Puede haber varios por día."""

    __tablename__ = "garage_charges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    day_id: Mapped[str] = mapped_column(ForeignKey("garage_days.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    day: Mapped[GarageDay] = relationship(back_populates="charges")


class Payment(Base):
    """Pago hecho al garaje."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    #: Producto del catálogo (del dueño de la lista) al que corresponde el elemento.
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    #: Foto propia del elemento (reemplaza la del producto solo aquí).
    image_key: Mapped[str | None] = mapped_column(String(300))
    image_size: Mapped[int | None] = mapped_column()

    checklist: Mapped[Checklist] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(lazy="selectin")


class Product(Timestamps, Base):
    """Producto del catálogo de un usuario ("Leche"), con foto opcional. Ver docs/PLAN-FOTOS.md."""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("owner_id", "normalized_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200))
    image_key: Mapped[str | None] = mapped_column(String(300))
    image_size: Mapped[int | None] = mapped_column()
    image_url: Mapped[str | None] = mapped_column(String(2000))


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


class EmailCode(Base):
    """Código de un solo uso enviado por correo (verificar cuenta o recuperar contraseña)."""

    __tablename__ = "email_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # register | reset
    #: HMAC-SHA256 del código: nunca se guarda el código en claro.
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invite(Base):
    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    list_id: Mapped[str] = mapped_column(ForeignKey("checklists.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
