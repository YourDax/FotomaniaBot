"""Pydantic-схемы запросов для API приложения."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

TaskStatus = str

TASK_STATUS_PATTERN = (
    "^(PENDING|PROCESSING|REQUIRES_REVIEW|CONTACT_NOT_FOUND|MAX_ERROR|"
    "SENT|FAILED|UNKNOWN|CANCELLED)$"
)


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = None
    max_user_id: str | None = None
    username: str | None = None
    chat_link: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    consent_basis: str | None = None
    opted_out: bool = False
    school_id: int | None = None
    class_id: int | None = None
    role: str = Field(default="KR", pattern="^(KR|RK)$")


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    message: str = Field(default="", max_length=4000)
    message_kr: str | None = Field(default=None, max_length=4000)
    message_rk: str | None = Field(default=None, max_length=4000)
    client_ids: list[int] = Field(default_factory=list)
    school_id: int | None = None


class CampaignMessagesIn(BaseModel):
    message_kr: str | None = Field(default=None, max_length=4000)
    message_rk: str | None = Field(default=None, max_length=4000)


class TaskMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ImportConfirm(BaseModel):
    rows: list[dict[str, Any]]
    mapping: dict[str, str] = Field(default_factory=dict)
    duplicate_mode: str = Field(default="skip", pattern="^(skip|update|new_only)$")


class ClassIn(BaseModel):
    school_name: str = Field(min_length=1, max_length=200)
    class_name: str = Field(min_length=1, max_length=100)


class SchoolUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ClassUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ContactImport(BaseModel):
    rows: list[dict[str, Any]]
    mapping: dict[str, str] = Field(default_factory=dict)
    school_name: str | None = None
    duplicate_mode: str = Field(default="skip", pattern="^(skip|update|new_only)$")


class ManualResultIn(BaseModel):
    result: str = Field(pattern="^(sent|failed|unknown)$")
    note: str | None = Field(default=None, max_length=500)


class TaskStatusIn(BaseModel):
    status: str = Field(pattern=TASK_STATUS_PATTERN)


class SettingsIn(BaseModel):
    mode: str = Field(default="manual", pattern="^manual$")


class CampaignDeleteIn(BaseModel):
    campaign_ids: list[int] = Field(min_length=1, max_length=500)


class ClientDeleteIn(BaseModel):
    client_ids: list[int] = Field(min_length=1, max_length=500)


class LoginIn(BaseModel):
    password: str = Field(min_length=8)
