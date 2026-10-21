"""Настройки приложения."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..db import session_scope
from ..models import (
    Setting,
)
from ..schemas import (
    SettingsIn,
)

log = logging.getLogger("fotomaniabot")
router = APIRouter()


@router.patch("/api/settings")
def update_settings(data: SettingsIn) -> dict[str, str]:
    with session_scope() as session:
        setting = session.get(Setting, "delivery_mode")
        if setting is None:
            setting = Setting(key="delivery_mode", value="manual")
            session.add(setting)
        setting.value = "manual"
        session.commit()
    return {"mode": "manual"}


@router.get("/api/settings")
def get_settings() -> dict[str, str]:
    with session_scope() as session:
        setting = session.get(Setting, "delivery_mode")
        return {"mode": setting.value if setting else "manual"}
