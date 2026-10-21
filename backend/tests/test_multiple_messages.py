"""Несколько сообщений на роль: рассылка, задания, подготовка в MAX, миграция."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app
from app.max_browser import PreparationResult
from app.migrations import apply_migrations
from app.routers import tasks as tasks_router

client = TestClient(app)


def _contacts(suffix: str) -> tuple[dict, dict]:
    school = client.post(
        "/api/classes", json={"school_name": f"Школа {suffix}", "class_name": "5А"}
    ).json()
    common = {"school_id": school["school_id"], "class_id": school["class_id"]}
    kr = client.post(
        "/api/clients",
        json={"name": f"КР {suffix}", "phone": f"+7999{suffix[:7]}", "role": "KR", **common},
    ).json()
    rk = client.post(
        "/api/clients",
        json={"name": f"РК {suffix}", "phone": f"+7998{suffix[:7]}", "role": "RK", **common},
    ).json()
    return kr, rk


def _campaign(suffix: str, **payload) -> tuple[dict, dict, dict]:
    kr, rk = _contacts(suffix)
    response = client.post(
        "/api/campaigns",
        json={"name": f"Много {suffix}", "client_ids": [kr["id"], rk["id"]], **payload},
    )
    assert response.status_code == 200, response.text
    campaign = response.json()
    tasks = {
        item["role"]: item for item in client.get(f"/api/campaigns/{campaign['id']}/tasks").json()
    }
    return campaign, tasks["KR"], tasks["RK"]


def test_each_role_gets_its_own_number_of_messages():
    suffix = uuid4().hex
    campaign, kr_task, rk_task = _campaign(
        suffix,
        messages_kr=["КР раз, {name}", "КР два", "КР три"],
        messages_rk=["РК раз, {name}", "РК два"],
    )
    assert campaign["task_count"] == 2
    assert campaign["messages_kr"] == ["КР раз, {name}", "КР два", "КР три"]
    assert campaign["messages_rk"] == ["РК раз, {name}", "РК два"]
    assert [m["text"] for m in kr_task["messages"]] == [
        f"КР раз, КР {suffix}",
        "КР два",
        "КР три",
    ]
    assert [m["index"] for m in rk_task["messages"]] == [1, 2]
    assert kr_task["message"] == f"КР раз, КР {suffix}"
    assert all(m["prepared_at"] is None for m in kr_task["messages"])


def test_single_message_api_still_works_and_other_role_falls_back():
    suffix = uuid4().hex
    campaign, kr_task, rk_task = _campaign(suffix, message_kr="Привет, {name}", message="Привет")
    assert campaign["messages_kr"] == ["Привет, {name}"]
    assert campaign["messages_rk"] == []
    assert [m["text"] for m in kr_task["messages"]] == [f"Привет, КР {suffix}"]
    assert [m["text"] for m in rk_task["messages"]] == [f"Привет, РК {suffix}"]


def test_invalid_message_lists_are_rejected():
    kr, _ = _contacts(uuid4().hex)
    base = {"name": "Плохая", "client_ids": [kr["id"]]}
    empty_inside = client.post("/api/campaigns", json={**base, "messages_kr": ["Один", "  "]})
    assert empty_inside.status_code == 422
    too_many = client.post("/api/campaigns", json={**base, "messages_kr": ["x"] * 6})
    assert too_many.status_code == 422
    too_long = client.post("/api/campaigns", json={**base, "messages_kr": ["x" * 4001]})
    assert too_long.status_code == 422


def test_prepare_uses_requested_message_and_marks_only_it(monkeypatch):
    suffix = uuid4().hex
    _, kr_task, _ = _campaign(suffix, messages_kr=["Первое", "Второе"], messages_rk=["Р"])
    sent_to_max: list[str] = []

    def fake_prepare(name, identity, message, expected_name=None):
        sent_to_max.append(message)
        return PreparationResult("DRAFT_PREPARED", "https://web.max.ru/chat", name, message)

    monkeypatch.setattr(tasks_router, "prepare_message", fake_prepare)
    response = client.post(f"/api/tasks/{kr_task['id']}/prepare-max?message_no=2")
    assert response.status_code == 200
    assert response.json()["message_no"] == 2
    assert sent_to_max == ["Второе"]

    saved = next(
        item
        for item in client.get(f"/api/campaigns/{kr_task['campaign_id']}/tasks").json()
        if item["id"] == kr_task["id"]
    )
    assert saved["messages"][0]["prepared_at"] is None
    assert saved["messages"][1]["prepared_at"] is not None
    assert saved["browser_prepared_at"] is not None

    default = client.post(f"/api/tasks/{kr_task['id']}/prepare-max")
    assert default.status_code == 200
    assert sent_to_max == ["Второе", "Первое"]


def test_prepare_rejects_missing_message_number(monkeypatch):
    _, kr_task, _ = _campaign(uuid4().hex, messages_kr=["Первое"], messages_rk=["Р"])
    monkeypatch.setattr(
        tasks_router,
        "prepare_message",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("MAX не должен вызываться")),
    )
    assert client.post(f"/api/tasks/{kr_task['id']}/prepare-max?message_no=2").status_code == 422
    assert client.post(f"/api/tasks/{kr_task['id']}/prepare-max?message_no=0").status_code == 422
    assert client.post(f"/api/tasks/{kr_task['id']}/prepare-max?message_no=abc").status_code == 422


def test_failed_prepare_does_not_mark_message(monkeypatch):
    from app.max_browser import MaxBrowserError

    _, kr_task, _ = _campaign(uuid4().hex, messages_kr=["Первое", "Второе"], messages_rk=["Р"])

    def boom(*args, **kwargs):
        raise MaxBrowserError("MAX недоступен")

    monkeypatch.setattr(tasks_router, "prepare_message", boom)
    assert client.post(f"/api/tasks/{kr_task['id']}/prepare-max?message_no=2").status_code == 502
    saved = next(
        item
        for item in client.get(f"/api/campaigns/{kr_task['campaign_id']}/tasks").json()
        if item["id"] == kr_task["id"]
    )
    assert all(m["prepared_at"] is None for m in saved["messages"])
    assert saved["browser_error"] == "MAX недоступен"
    # блокировка освобождена после ошибки
    assert not tasks_router.max_lock.locked()


def test_parallel_max_operation_is_rejected(monkeypatch):
    _, kr_task, _ = _campaign(uuid4().hex, messages_kr=["Первое"], messages_rk=["Р"])
    monkeypatch.setattr(
        tasks_router,
        "prepare_message",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("не должен вызываться")),
    )
    assert tasks_router.max_lock.acquire(blocking=False)
    try:
        assert client.post(f"/api/tasks/{kr_task['id']}/prepare-max").status_code == 409
        assert client.post(f"/api/tasks/{kr_task['id']}/open-max").status_code == 409
        assert client.post(f"/api/tasks/{kr_task['id']}/rename-max").status_code in {409, 422}
    finally:
        tasks_router.max_lock.release()


def test_edit_single_message_resets_only_its_draft(monkeypatch):
    _, kr_task, _ = _campaign(uuid4().hex, messages_kr=["Первое", "Второе"], messages_rk=["Р"])
    monkeypatch.setattr(
        tasks_router,
        "prepare_message",
        lambda name, identity, message, expected_name=None: PreparationResult(
            "DRAFT_PREPARED", "u", name, message
        ),
    )
    for number in (1, 2):
        assert client.post(f"/api/tasks/{kr_task['id']}/prepare-max?message_no={number}").status_code == 200

    edited = client.patch(
        f"/api/tasks/{kr_task['id']}/message", json={"message": "Второе (новое)", "index": 2}
    )
    assert edited.status_code == 200
    saved = next(
        item
        for item in client.get(f"/api/campaigns/{kr_task['campaign_id']}/tasks").json()
        if item["id"] == kr_task["id"]
    )
    assert saved["messages"][0]["text"] == "Первое"
    assert saved["messages"][0]["prepared_at"] is not None
    assert saved["messages"][1]["text"] == "Второе (новое)"
    assert saved["messages"][1]["prepared_at"] is None

    out_of_range = client.patch(
        f"/api/tasks/{kr_task['id']}/message", json={"message": "x", "index": 3}
    )
    assert out_of_range.status_code == 422
    assert client.patch(
        f"/api/tasks/{kr_task['id']}/message", json={"message": "x", "index": 0}
    ).status_code == 422
    # без index правится первое сообщение (прежнее поведение API)
    assert client.patch(
        f"/api/tasks/{kr_task['id']}/message", json={"message": "Первое (новое)"}
    ).status_code == 200


def test_changing_campaign_messages_changes_count_and_keeps_unchanged_drafts(monkeypatch):
    campaign, kr_task, rk_task = _campaign(
        uuid4().hex, messages_kr=["Первое", "Второе"], messages_rk=["Р1", "Р2"]
    )
    monkeypatch.setattr(
        tasks_router,
        "prepare_message",
        lambda name, identity, message, expected_name=None: PreparationResult(
            "DRAFT_PREPARED", "u", name, message
        ),
    )
    assert client.post(f"/api/tasks/{kr_task['id']}/prepare-max?message_no=1").status_code == 200

    result = client.patch(
        f"/api/campaigns/{campaign['id']}/messages",
        json={"messages_kr": ["Первое", "Второе", "Третье"], "messages_rk": ["Р1"]},
    )
    assert result.status_code == 200
    assert result.json()["campaign"]["messages_kr"] == ["Первое", "Второе", "Третье"]
    by_role = {
        item["role"]: item for item in client.get(f"/api/campaigns/{campaign['id']}/tasks").json()
    }
    assert [m["text"] for m in by_role["KR"]["messages"]] == ["Первое", "Второе", "Третье"]
    assert by_role["KR"]["messages"][0]["prepared_at"] is not None  # текст не менялся
    assert [m["text"] for m in by_role["RK"]["messages"]] == ["Р1"]

    empty = client.patch(f"/api/campaigns/{campaign['id']}/messages", json={"messages_kr": [], "messages_rk": []})
    assert empty.status_code == 422
    blank = client.patch(f"/api/campaigns/{campaign['id']}/messages", json={"messages_kr": ["а", ""]})
    assert blank.status_code == 422


def test_sent_tasks_keep_their_messages_when_campaign_texts_change():
    campaign, kr_task, _ = _campaign(uuid4().hex, messages_kr=["Первое", "Второе"], messages_rk=["Р"])
    confirmed = client.post(f"/api/tasks/{kr_task['id']}/confirm", json={"result": "sent"})
    assert confirmed.status_code == 200
    result = client.patch(
        f"/api/campaigns/{campaign['id']}/messages", json={"messages_kr": ["Новое"], "messages_rk": ["Р"]}
    )
    assert result.json()["skipped"] >= 1
    saved = next(
        item
        for item in client.get(f"/api/campaigns/{campaign['id']}/tasks").json()
        if item["id"] == kr_task["id"]
    )
    assert [m["text"] for m in saved["messages"]] == ["Первое", "Второе"]


def test_report_counts_prepared_messages(monkeypatch):
    campaign, kr_task, _ = _campaign(uuid4().hex, messages_kr=["Первое", "Второе"], messages_rk=["Р"])
    monkeypatch.setattr(
        tasks_router,
        "prepare_message",
        lambda name, identity, message, expected_name=None: PreparationResult(
            "DRAFT_PREPARED", "u", name, message
        ),
    )
    client.post(f"/api/tasks/{kr_task['id']}/prepare-max?message_no=2")
    csv_text = client.get(f"/api/reports/{campaign['id']}/export").content.decode("utf-8")
    assert "Сообщений подготовлено" in csv_text
    assert "1 из 2" in csv_text
    assert "0 из 1" in csv_text


def test_migration_adds_multiple_message_columns_to_old_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE clients (id INTEGER PRIMARY KEY, name VARCHAR(200))",
            "CREATE TABLE settings (key VARCHAR(80) PRIMARY KEY, value TEXT)",
            "CREATE TABLE schools (id INTEGER PRIMARY KEY, name VARCHAR(200))",
            "CREATE TABLE school_classes (id INTEGER PRIMARY KEY, school_id INTEGER, name VARCHAR(100))",
            "CREATE TABLE campaigns (id INTEGER PRIMARY KEY, name VARCHAR(200), mode VARCHAR(20), "
            "message TEXT, message_kr TEXT, message_rk TEXT, school_id INTEGER)",
            "CREATE TABLE delivery_tasks (id INTEGER PRIMARY KEY, campaign_id INTEGER, "
            "client_id INTEGER, rendered_message TEXT, recipient_role VARCHAR(10), opened_at DATETIME, "
            "operator_confirmed_at DATETIME, operator_result VARCHAR(30), "
            "browser_prepared_at DATETIME, browser_error TEXT)",
            "INSERT INTO campaigns (id, name, mode, message, message_kr) "
            "VALUES (1, 'Старая', 'manual', 'Привет', 'Привет')",
            "INSERT INTO delivery_tasks (id, campaign_id, client_id, rendered_message, recipient_role) "
            "VALUES (1, 1, 1, 'Привет, Иван', 'KR')",
        ):
            connection.execute(text(statement))
    apply_migrations(engine)
    apply_migrations(engine)  # повторный запуск безопасен
    with engine.begin() as connection:
        campaign_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(campaigns)"))}
        task_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(delivery_tasks)"))}
    assert {"messages_kr", "messages_rk"} <= campaign_columns
    assert "messages" in task_columns


def test_legacy_task_without_messages_column_value_shows_single_message():
    from app.message_sets import task_messages
    from app.models import DeliveryTask

    legacy = DeliveryTask(campaign_id=1, client_id=1, rendered_message="Старый текст")
    assert task_messages(legacy) == [{"text": "Старый текст", "prepared_at": None}]
    empty = DeliveryTask(campaign_id=1, client_id=1, rendered_message="")
    assert task_messages(empty) == []
