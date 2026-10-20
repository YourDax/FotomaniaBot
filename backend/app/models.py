"""SQLAlchemy models — единственное описание схемы данных приложения."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, engine

__all__ = [
    "Base",
    "Campaign",
    "Client",
    "DeliveryTask",
    "MessageTemplate",
    "School",
    "SchoolClass",
    "Setting",
    "engine",
    "now",
]


def now() -> datetime:
    return datetime.now(timezone.utc)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class School(Base):
    __tablename__ = "schools"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SchoolClass(Base):
    __tablename__ = "school_classes"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_school_class_name"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    max_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    chat_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    custom_fields: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(50), default="manual")
    consent_basis: Mapped[str | None] = mapped_column(String(200), nullable=True)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=True, index=True
    )
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(10), default="KR", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text)
    message_kr: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_rk: Mapped[str | None] = mapped_column(Text, nullable=True)
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tasks: Mapped[list["DeliveryTask"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class DeliveryTask(Base):
    __tablename__ = "delivery_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    recipient_role: Mapped[str] = mapped_column(String(10), default="KR")
    rendered_message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operator_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    operator_result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    browser_prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    browser_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    campaign: Mapped[Campaign] = relationship(back_populates="tasks")


class MessageTemplate(Base):
    """Использованный текст рассылки для одной роли (КР или РК), хранится без персональных данных."""

    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("role", "body", name="uq_message_template_role_body"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(10), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )

