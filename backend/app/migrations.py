"""Small, ordered SQLite migrations for the local single-user application."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine


class MigrationError(RuntimeError):
    """Raised when an ordered migration cannot be applied."""


MIGRATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "0001_school_and_role_fields",
        (
            "ALTER TABLE clients ADD COLUMN school_id INTEGER REFERENCES schools(id)",
            "ALTER TABLE clients ADD COLUMN class_id INTEGER REFERENCES school_classes(id)",
            "ALTER TABLE clients ADD COLUMN role VARCHAR(10) NOT NULL DEFAULT 'KR'",
        ),
    ),
    (
        "0002_campaign_role_messages",
        (
            "ALTER TABLE campaigns ADD COLUMN message_kr TEXT",
            "ALTER TABLE campaigns ADD COLUMN message_rk TEXT",
            "ALTER TABLE campaigns ADD COLUMN school_id INTEGER REFERENCES schools(id)",
        ),
    ),
    (
        "0003_task_manual_review_fields",
        (
            "ALTER TABLE delivery_tasks ADD COLUMN recipient_role VARCHAR(10) NOT NULL DEFAULT 'KR'",
            "ALTER TABLE delivery_tasks ADD COLUMN opened_at DATETIME",
            "ALTER TABLE delivery_tasks ADD COLUMN operator_confirmed_at DATETIME",
            "ALTER TABLE delivery_tasks ADD COLUMN operator_result VARCHAR(30)",
            "ALTER TABLE delivery_tasks ADD COLUMN browser_prepared_at DATETIME",
            "ALTER TABLE delivery_tasks ADD COLUMN browser_error TEXT",
        ),
    ),
    (
        "0005_multiple_messages",
        (
            "ALTER TABLE campaigns ADD COLUMN messages_kr TEXT",
            "ALTER TABLE campaigns ADD COLUMN messages_rk TEXT",
            "ALTER TABLE delivery_tasks ADD COLUMN messages TEXT",
        ),
    ),
    (
        "0006_task_campaign_status_index",
        (
            "CREATE INDEX IF NOT EXISTS ix_delivery_tasks_campaign_status "
            "ON delivery_tasks(campaign_id, status)",
        ),
    ),
    (
        "0007_task_updated_at",
        (
            "ALTER TABLE delivery_tasks ADD COLUMN updated_at DATETIME",
            "UPDATE delivery_tasks SET updated_at = COALESCE(finished_at, started_at, created_at) "
            "WHERE updated_at IS NULL",
        ),
    ),
)


# 0004 применяется отдельно после цикла; 0005_multiple_campaign_messages — прежнее имя
# нынешней 0005_multiple_messages (базы разработки хранят обе записи).
LEGACY_REVISIONS = frozenset({"0004_unique_school_class", "0005_multiple_campaign_messages"})
KNOWN_REVISIONS = frozenset(revision for revision, _ in MIGRATIONS) | LEGACY_REVISIONS
KEEP_BACKUPS = 5


def backup_before_upgrade(engine: Engine) -> Path | None:
    """Перед миграцией существующей базы сохраняет её копию в `backups/` рядом с файлом.

    Если база уже создана более новой версией приложения (в ней есть неизвестные
    ревизии), запуск прерывается: старый код не должен менять чужую схему.
    Новая и актуальная базы не копируются. Возвращает путь к копии или None.
    """
    database = engine.url.database
    if engine.dialect.name != "sqlite" or not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.is_file() or path.stat().st_size == 0:
        return None
    source = sqlite3.connect(str(path))
    try:
        tables = {
            row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "clients" not in tables:
            return None  # не наша схема или пустая база: мигрировать нечего
        applied: set[str] = set()
        if "schema_migrations" in tables:
            applied = {row[0] for row in source.execute("SELECT revision FROM schema_migrations")}
        newer = sorted(applied - KNOWN_REVISIONS)
        if newer:
            raise MigrationError(
                f"База данных создана более новой версией приложения (ревизии: {', '.join(newer)}). "
                "Запустите свежую версию приложения или восстановите копию из папки backups."
            )
        if not KNOWN_REVISIONS - applied:
            return None
        backups = path.parent / "backups"
        backups.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = backups / f"{path.stem}-before-upgrade-{stamp}.db"
        try:
            copy = sqlite3.connect(str(target))
            try:
                source.backup(copy)
            finally:
                copy.close()
        except (OSError, sqlite3.Error) as exc:
            target.unlink(missing_ok=True)
            raise MigrationError(
                f"Не удалось сохранить резервную копию базы перед обновлением: {exc}. "
                "Проверьте свободное место и права на папку данных."
            ) from exc
    finally:
        source.close()
    for stale in sorted(backups.glob(f"{path.stem}-before-upgrade-*.db"))[:-KEEP_BACKUPS]:
        stale.unlink(missing_ok=True)
    return target


def _apply_statement(connection: object, statement: str) -> None:
    """Выполняет оператор миграции; ADD COLUMN пропускается, если колонка уже есть."""
    if " ADD COLUMN " not in statement:
        connection.exec_driver_sql(statement)
        return
    table = statement.split(" ADD COLUMN ", 1)[0].split("ALTER TABLE ", 1)[1]
    column = statement.split(" ADD COLUMN ", 1)[1].split()[0]
    existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").all()}
    if column not in existing:
        connection.exec_driver_sql(statement)


def _dedupe_school_classes(connection: object) -> None:
    """Keep the oldest class per (school_id, name) and repoint its contacts."""
    connection.exec_driver_sql(
        "DELETE FROM school_classes WHERE id NOT IN "
        "(SELECT MIN(id) FROM school_classes GROUP BY school_id, name)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_school_class_name "
        "ON school_classes(school_id, name)"
    )


def apply_migrations(engine: Engine) -> None:
    """Apply each missing revision once; tolerate columns created by newer metadata."""
    try:
        with engine.begin() as connection:
            existing_tables = set(
                connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")
                .scalars()
                .all()
            )
            # A completely new database already has the current schema from metadata.
            if not {"clients", "campaigns", "delivery_tasks"}.issubset(existing_tables):
                return
            connection.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(revision VARCHAR(100) PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = set(
                connection.exec_driver_sql("SELECT revision FROM schema_migrations").scalars().all()
            )
            for revision, statements in MIGRATIONS:
                if revision in applied:
                    continue
                for statement in statements:
                    _apply_statement(connection, statement)
                if revision == "0003_task_manual_review_fields":
                    connection.exec_driver_sql(
                        "UPDATE campaigns SET mode = 'manual' WHERE mode = 'simulator'"
                    )
                    if "settings" in existing_tables:  # таблица осталась только в старых базах
                        connection.exec_driver_sql(
                            "UPDATE settings SET value = 'manual' "
                            "WHERE key = 'delivery_mode' AND value = 'simulator'"
                        )
                connection.exec_driver_sql(
                    "INSERT INTO schema_migrations (revision) VALUES (?)", (revision,)
                )
            if "0004_unique_school_class" not in applied:
                _dedupe_school_classes(connection)
                connection.exec_driver_sql(
                    "INSERT INTO schema_migrations (revision) VALUES (?)",
                    ("0004_unique_school_class",),
                )
    except MigrationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise MigrationError(f"Не удалось применить миграции базы данных: {exc}") from exc
