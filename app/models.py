"""Tablas de la base de datos (SQLAlchemy 2)."""

import uuid
import datetime as dt
from datetime import UTC, datetime

from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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


class Device(Base):
    """Teléfono de un usuario registrado para recibir notificaciones push (token de FCM)."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(512), unique=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    """Código para unirse a una lista o a una sección de recordatorios (uno de los dos)."""

    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    list_id: Mapped[str | None] = mapped_column(ForeignKey("checklists.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str | None] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- recordatorios (ver garaje-android/docs/PLAN-RECORDATORIOS.md)

class Space(Timestamps, Base):
    """Sección de recordatorios de un usuario (Pagos, Mi hogar, Mi carro). Se comparte completa."""

    __tablename__ = "spaces"
    __table_args__ = (UniqueConstraint("owner_id", "kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # payments | home | car | other

    owner: Mapped[User] = relationship(lazy="selectin")
    members: Mapped[list["SpaceMember"]] = relationship(
        back_populates="space",
        cascade="all, delete-orphan",
        order_by="SpaceMember.invited_at",
    )
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="space", cascade="all, delete-orphan")


class SpaceMember(Base):
    """Persona con acceso a una sección. Igual que ListMember: user_id se llena al aceptar."""

    __tablename__ = "space_members"
    __table_args__ = (UniqueConstraint("space_id", "email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # editor | viewer
    status: Mapped[str] = mapped_column(String(16))  # pending | accepted
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    space: Mapped[Space] = relationship(back_populates="members")


class Reminder(Timestamps, Base):
    """Algo que vence cada cierto tiempo (la luz cada mes) o una sola vez."""

    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    #: Monto estimado (la luz cambia cada mes; el real se guarda al marcarlo).
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    #: Cada cuánto se repite: every=1, unit="month" → cada mes. Ambos vacíos = una sola vez.
    every: Mapped[int | None] = mapped_column(Integer)
    unit: Mapped[str | None] = mapped_column(String(8))  # day | week | month | year
    #: Día del mes original: si vence el 31, en febrero vence el 28 y en marzo vuelve al 31.
    anchor_day: Mapped[int | None] = mapped_column(Integer)
    next_due: Mapped[dt.date] = mapped_column(Date)
    notify_days_before: Mapped[int] = mapped_column(Integer, default=2)
    #: Desde dónde se cuenta el siguiente: "due" (la fecha que vencía, ej. la luz) o
    #: "done" (el día que se hizo, ej. limpiar el aire cada 3 meses desde la última limpieza).
    count_from: Mapped[str] = mapped_column(String(8), default="due", server_default="due")
    #: Mi carro: también cada tantos km (ej. aceite cada 3 meses o 5.000 km). Solo informativo:
    #: los avisos son por fecha; la app muestra a qué kilometraje toca según el último registrado.
    every_km: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    #: Recordatorio de una sola vez ya hecho.
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    space: Mapped[Space] = relationship(back_populates="reminders")
    logs: Mapped[list["ReminderLog"]] = relationship(
        back_populates="reminder",
        cascade="all, delete-orphan",
        order_by="desc(ReminderLog.created_at)",
    )


class ReminderLog(Base):
    """Historial: cada vez que se marcó como pagado/hecho."""

    __tablename__ = "reminder_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reminder_id: Mapped[str] = mapped_column(ForeignKey("reminders.id", ondelete="CASCADE"), index=True)
    #: Vencimiento que se cubrió (para deshacer: vuelve a ser el próximo).
    due_date: Mapped[dt.date] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    note: Mapped[str | None] = mapped_column(String(200))
    #: Kilometraje del carro cuando se hizo (Mi carro).
    odometer: Mapped[int | None] = mapped_column(Integer)
    done_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    done_by_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    reminder: Mapped[Reminder] = relationship(back_populates="logs")
