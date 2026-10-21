"""Small, ordered SQLite migrations for the local single-user application."""

from __future__ import annotations

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
