"""Единая точка доступа к базе данных.

Модуль содержит только инфраструктуру SQLAlchemy: `Base`, `engine`,
`SessionLocal` и фабрику сессий `db()`. Модели живут в `models.py`,
поэтому ни один другой модуль не должен создавать собственный engine.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .data_dir import DB_PATH, adopt_legacy_database

BASE_DIR = Path(__file__).resolve().parents[1]
if "DATABASE_URL" not in os.environ:
    adopt_legacy_database()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")


class Base(DeclarativeBase):
    """Базовый класс всех ORM-моделей приложения."""


_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
    """Параметры SQLite: внешние ключи (по умолчанию выключены), WAL и ожидание блокировки."""
    if not _is_sqlite:
        return
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL: читатели не блокируют запись (воркер и запросы работают из разных потоков);
    # busy_timeout: вместо мгновенного «database is locked» ждём освобождения до 5 с.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Сессия с гарантированным закрытием и откатом при ошибке."""
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
