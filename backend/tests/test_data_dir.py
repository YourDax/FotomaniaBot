"""Данные живут вне папки приложения: перенос старой базы, резервная копия и защита от «откатов»."""

import sqlite3

import pytest
from sqlalchemy import create_engine

from app import data_dir
from app.migrations import KEEP_BACKUPS, KNOWN_REVISIONS, MigrationError, backup_before_upgrade


def _old_database(path, revisions=()):
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE campaigns (id INTEGER PRIMARY KEY);"
        "CREATE TABLE delivery_tasks (id INTEGER PRIMARY KEY);"
        "INSERT INTO clients (name) VALUES ('Иванова');"
    )
    if revisions:
        connection.execute(
            "CREATE TABLE schema_migrations (revision TEXT PRIMARY KEY, applied_at TEXT)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations (revision) VALUES (?)", [(r,) for r in revisions]
        )
    connection.commit()
    connection.close()


def _engine(path):
    return create_engine(f"sqlite:///{path.as_posix()}")


def test_missing_or_empty_database_is_not_backed_up(tmp_path):
    assert backup_before_upgrade(_engine(tmp_path / "none.db")) is None
    (tmp_path / "empty.db").write_bytes(b"")
    assert backup_before_upgrade(_engine(tmp_path / "empty.db")) is None


def test_outdated_database_is_backed_up_with_its_data(tmp_path):
    path = tmp_path / "app.db"
    _old_database(path)
    backup = backup_before_upgrade(_engine(path))
    assert backup is not None and backup.parent == tmp_path / "backups"
    copy = sqlite3.connect(backup)
    assert copy.execute("SELECT name FROM clients").fetchall() == [("Иванова",)]
    copy.close()


def test_up_to_date_database_is_not_backed_up(tmp_path):
    path = tmp_path / "app.db"
    _old_database(path, revisions=sorted(KNOWN_REVISIONS))
    assert backup_before_upgrade(_engine(path)) is None
    assert not (tmp_path / "backups").exists()


def test_renamed_legacy_revision_is_not_treated_as_newer(tmp_path):
    path = tmp_path / "app.db"
    _old_database(path, revisions=sorted(KNOWN_REVISIONS))  # в наборе есть и прежнее имя 0005
    assert "0005_multiple_campaign_messages" in KNOWN_REVISIONS
    assert backup_before_upgrade(_engine(path)) is None


def test_database_from_newer_version_is_refused_untouched(tmp_path):
    path = tmp_path / "app.db"
    _old_database(path, revisions=[*sorted(KNOWN_REVISIONS), "9999_from_the_future"])
    with pytest.raises(MigrationError, match="9999_from_the_future"):
        backup_before_upgrade(_engine(path))
    assert not (tmp_path / "backups").exists()


def test_only_latest_backups_are_kept(tmp_path):
    path = tmp_path / "app.db"
    _old_database(path)
    backups = tmp_path / "backups"
    backups.mkdir()
    for number in range(KEEP_BACKUPS + 3):
        (backups / f"app-before-upgrade-2000010{number}-000000.db").write_bytes(b"x")
    new = backup_before_upgrade(_engine(path))
    kept = sorted(backups.glob("app-before-upgrade-*.db"))
    assert len(kept) == KEEP_BACKUPS and new in kept


def test_legacy_database_is_copied_once_and_left_in_place(tmp_path, monkeypatch):
    legacy_backend = tmp_path / "old" / "backend"
    legacy_backend.mkdir(parents=True)
    _old_database(legacy_backend / "fotomaniabot.db")
    target = tmp_path / "data" / "fotomaniabot.db"
    target.parent.mkdir()
    monkeypatch.setattr(data_dir, "BACKEND_DIR", legacy_backend)
    monkeypatch.setattr(data_dir, "DB_PATH", target)

    data_dir.adopt_legacy_database()
    copied = sqlite3.connect(target)
    assert copied.execute("SELECT name FROM clients").fetchall() == [("Иванова",)]
    copied.close()
    assert (legacy_backend / "fotomaniabot.db").exists()

    copied = sqlite3.connect(target)
    copied.execute("DELETE FROM clients")
    copied.commit()
    copied.close()
    data_dir.adopt_legacy_database()  # существующая база не перезаписывается
    copied = sqlite3.connect(target)
    assert copied.execute("SELECT COUNT(*) FROM clients").fetchone() == (0,)
    copied.close()


def test_legacy_profile_is_moved_once(tmp_path, monkeypatch):
    old_root = tmp_path / "old"
    (old_root / ".max-browser-profile").mkdir(parents=True)
    (old_root / ".max-browser-profile" / "Cookies").write_text("session")
    profile = tmp_path / "data" / "browser-profile"
    profile.parent.mkdir()
    monkeypatch.setattr(data_dir, "APP_ROOT", old_root)
    monkeypatch.setattr(data_dir, "PROFILE_DIR", profile)

    data_dir.adopt_legacy_profile()
    assert (profile / "Cookies").read_text() == "session"
    assert not (old_root / ".max-browser-profile").exists()
    data_dir.adopt_legacy_profile()  # повторный вызов безопасен
    assert (profile / "Cookies").exists()
