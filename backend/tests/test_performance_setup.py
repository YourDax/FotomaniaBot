"""Настройки SQLite и агрегирование статусов одним запросом."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.db import engine
from app.main import app

client = TestClient(app)


def test_sqlite_uses_wal_and_busy_timeout():
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_campaign_index_exists_on_fresh_database():
    with engine.connect() as connection:
        indexes = {row[1] for row in connection.execute(text("PRAGMA index_list(delivery_tasks)"))}
    assert "ix_delivery_tasks_campaign_status" in indexes


def _count_queries(action) -> int:
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(statements)


def test_listing_queries_do_not_grow_with_data():
    suffix = uuid4().hex[:8]
    for number in range(4):
        created = client.post(
            "/api/classes",
            json={"school_name": f"Школа {suffix} {number}", "class_name": f"{number}А"},
        ).json()
        contact = client.post(
            "/api/clients",
            json={
                "name": f"КР {suffix} {number}",
                "role": "KR",
                "school_id": created["school_id"],
                "class_id": created["class_id"],
            },
        ).json()
        client.post(
            "/api/campaigns",
            json={
                "name": f"Р {suffix} {number}",
                "client_ids": [contact["id"]],
                "message_kr": "Текст",
            },
        )
    assert _count_queries(lambda: client.get("/api/schools")) <= 4
    assert _count_queries(lambda: client.get("/api/campaigns")) <= 3

    schools = client.get("/api/schools").json()
    mine = [item for item in schools if item["name"].startswith(f"Школа {suffix}")]
    assert len(mine) == 4
    assert all(
        len(item["classes"]) == 1 and len(item["classes"][0]["contacts"]) == 1 for item in mine
    )
    campaigns = [
        item
        for item in client.get("/api/campaigns").json()
        if item["name"].startswith(f"Р {suffix}")
    ]
    assert len(campaigns) == 4
    assert all(
        item["task_count"] == 1 and item["status_counts"] == {"PENDING": 1} for item in campaigns
    )


def _campaign_with_tasks(count: int) -> tuple[int, list[int]]:
    suffix = uuid4().hex[:8]
    created = client.post(
        "/api/classes", json={"school_name": f"Школа {suffix}", "class_name": "7А"}
    ).json()
    ids = []
    for number in range(count):
        contact = client.post(
            "/api/clients",
            json={
                "name": f"КР {suffix} {number}",
                "role": "KR",
                "school_id": created["school_id"],
                "class_id": created["class_id"],
            },
        ).json()
        ids.append(contact["id"])
    campaign = client.post(
        "/api/campaigns", json={"name": f"И {suffix}", "client_ids": ids, "message_kr": "Текст"}
    ).json()
    return campaign["id"], ids


def test_task_changes_return_only_modified_tasks(monkeypatch):
    import time
    from datetime import timedelta

    from app.routers import campaigns

    monkeypatch.setattr(campaigns, "CHANGES_CURSOR_OVERLAP", timedelta(0))
    campaign_id, _ = _campaign_with_tasks(3)
    first = client.get(f"/api/campaigns/{campaign_id}/tasks/changes").json()
    assert len(first["changed"]) == 3
    assert first["ids"] == [item["id"] for item in first["changed"]]
    assert first["changed"][0]["updated_at"] is not None

    time.sleep(0.05)
    quiet = client.get(
        f"/api/campaigns/{campaign_id}/tasks/changes", params={"since": first["cursor"]}
    ).json()
    assert quiet["changed"] == []
    assert quiet["ids"] == first["ids"]

    target = first["ids"][1]
    assert client.patch(f"/api/tasks/{target}/status", json={"status": "SENT"}).status_code == 200
    changed = client.get(
        f"/api/campaigns/{campaign_id}/tasks/changes", params={"since": quiet["cursor"]}
    ).json()
    assert [item["id"] for item in changed["changed"]] == [target]
    assert changed["changed"][0]["status"] == "SENT"


def test_task_changes_report_removed_tasks_and_validate_input():
    campaign_id, contact_ids = _campaign_with_tasks(2)
    before = client.get(f"/api/campaigns/{campaign_id}/tasks/changes").json()
    assert client.delete(f"/api/clients/{contact_ids[0]}").status_code == 200
    after = client.get(
        f"/api/campaigns/{campaign_id}/tasks/changes", params={"since": before["cursor"]}
    ).json()
    assert len(after["ids"]) == 1
    assert client.get("/api/campaigns/999999/tasks/changes").status_code == 404
    assert (
        client.get(f"/api/campaigns/{campaign_id}/tasks/changes?since=не-дата").status_code == 422
    )
    naive = client.get(f"/api/campaigns/{campaign_id}/tasks/changes?since=2000-01-01T00:00:00")
    assert naive.status_code == 200
    assert len(naive.json()["changed"]) == 1
