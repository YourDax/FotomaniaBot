"""Каталог данных вне папки приложения.

База, журналы и профиль браузера MAX живут в постоянном каталоге пользователя
(`%LOCALAPPDATA%\\MAX-Rassylki`, переопределяется переменной `MAX_DATA_DIR`).
Поэтому новая версия, распакованная в другую папку, продолжает работать с теми же
данными, а схема базы обновляется миграциями, а не создаётся заново.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger("fotomaniabot")

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_DIR.parent


def _resolve_data_dir() -> Path:
    custom = os.getenv("MAX_DATA_DIR", "").strip()
    if custom:
        return Path(custom)
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "MAX-Rassylki"
    return Path.home() / ".max-rassylki"


DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "fotomaniabot.db"
LOG_DIR = DATA_DIR / "logs"
PROFILE_DIR = DATA_DIR / "browser-profile"

LOG_DIR.mkdir(parents=True, exist_ok=True)


def adopt_legacy_database() -> None:
    """Один раз копирует базу из папки старой версии (backend/fotomaniabot.db).

    Копирование идёт через sqlite3.backup, чтобы учесть недосброшенный WAL.
    Исходный файл не трогаем: при сбое остаётся откат на старую версию.
    """
    legacy = BACKEND_DIR / "fotomaniabot.db"
    if DB_PATH.exists() or not legacy.is_file() or legacy.stat().st_size == 0:
        return
    partial = DB_PATH.with_name(DB_PATH.name + ".importing")
    partial.unlink(missing_ok=True)
    try:
        source = sqlite3.connect(str(legacy))
        target = sqlite3.connect(str(partial))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        partial.replace(DB_PATH)  # файл появляется в каталоге данных только целиком
        log.warning("База контактов перенесена из %s в %s", legacy, DB_PATH)
    except (OSError, sqlite3.Error):
        partial.unlink(missing_ok=True)
        log.exception("Не удалось перенести базу из %s; приложение начнёт с пустой базой", legacy)


def adopt_legacy_profile() -> None:
    """Один раз копирует профиль браузера MAX (с авторизацией) из папки старой версии."""
    legacy = APP_ROOT / ".max-browser-profile"
    if PROFILE_DIR.exists() or not legacy.is_dir():
        return
    partial = PROFILE_DIR.with_name(PROFILE_DIR.name + ".importing")
    shutil.rmtree(partial, ignore_errors=True)
    try:
        shutil.copytree(legacy, partial)
        partial.replace(PROFILE_DIR)
    except OSError:
        # Чаще всего профиль открыт старым браузером: тогда MAX потребует войти заново.
        shutil.rmtree(partial, ignore_errors=True)
        log.exception("Не удалось перенести профиль браузера из %s", legacy)
        return
    shutil.rmtree(legacy, ignore_errors=True)
    log.warning("Профиль браузера MAX перенесён в %s", PROFILE_DIR)
