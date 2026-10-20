"""Regression tests for the API surface not covered by test_app.py."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def _make_school_class() -> tuple[int, int]:
    payload = client.post(
        "/api/classes",
        json={"school_name": f"Школа {uuid4()}", "class_name": "5А"},
    ).json()
    return payload["school_id"], payload["class_id"]


def test_duplicate_client_is_detected_by_username_not_only_first_field():
    username = f"user-{uuid4().hex}"
    first = client.post("/api/clients", json={"name": "Первый", "username": username})
    assert first.status_code == 200
    second = client.post(
        "/api/clients",
        json={"name": "Второй", "phone": "79990000009", "username": username},
    )
    assert second.status_code == 409


def test_duplicate_client_is_detected_by_chat_link():
    link = f"https://max.ru/{uuid4().hex}"
    assert client.post("/api/clients", json={"name": "Первый", "chat_link": link}).status_code == 200
    assert client.post("/api/clients", json={"name": "Второй", "chat_link": link}).status_code == 409


def test_duplicate_client_is_detected_by_max_user_id():
    max_user_id = f"max-{uuid4().hex}"
    assert client.post("/api/clients", json={"name": "Первый", "max_user_id": max_user_id}).status_code == 200
    assert client.post("/api/clients", json={"name": "Второй", "max_user_id": max_user_id}).status_code == 409


def test_client_rejects_class_from_another_school():
    first_school, _ = _make_school_class()
    _, second_class = _make_school_class()
    response = client.post(
        "/api/clients",
        json={"name": "Несогласованный", "school_id": first_school, "class_id": second_class},
    )
    assert response.status_code == 400
    assert "класс" in response.json()["detail"].lower()


def test_client_rejects_unknown_school():
    response = client.post("/api/clients", json={"name": "Без школы", "school_id": 999999})
    assert response.status_code == 400


def test_phone_is_normalized_on_create_and_update():
    created = client.post(
        "/api/clients", json={"name": "Телефон", "phone": "8 (999) 123-45-67"}
    ).json()
    assert created["phone"] == "+79991234567"
    updated = client.patch(
        f"/api/clients/{created['id']}", json={"name": "Телефон", "phone": "79991234568"}
    ).json()
    assert updated["phone"] == "+79991234568"


def test_import_confirm_updates_existing_client_on_request():
    link = f"https://max.ru/{uuid4().hex}"
    created = client.post("/api/clients", json={"name": "Старое имя", "chat_link": link}).json()
    response = client.post(
        "/api/imports/confirm",
        json={
            "rows": [{"Имя": "Новое имя", "Ссылка": link}],
            "mapping": {"Имя": "name", "Ссылка": "chat_link"},
            "duplicate_mode": "update",
        },
    ).json()
    assert response == {"created": 0, "updated": 1, "skipped": 0}
    clients = {item["id"]: item for item in client.get("/api/clients").json()}
    assert clients[created["id"]]["name"] == "Новое имя"


def test_import_confirm_skips_rows_without_name():
    response = client.post(
        "/api/imports/confirm",
        json={
            "rows": [{"Имя": "", "Телефон": "79990000000"}],
            "mapping": {"Имя": "name", "Телефон": "phone"},
            "duplicate_mode": "skip",
        },
    ).json()
    assert response["created"] == 0
    assert response["skipped"] == 1


def test_reports_export_returns_bom_prefixed_csv():
    contact = client.post("/api/clients", json={"name": f"Отчёт {uuid4().hex}"}).json()
    campaign = client.post(
        "/api/campaigns",
        json={"name": "Отчётная", "message": "Текст", "client_ids": [contact["id"]]},
    ).json()
    response = client.get(f"/api/reports/{campaign['id']}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "Кампания" in response.content.decode("utf-8")


def test_reports_export_missing_campaign_is_404():
    assert client.get("/api/reports/999999/export").status_code == 404


def test_auth_accepts_configured_credentials_and_rejects_wrong_password():
    password = f"secret-{uuid4().hex}"
    assert client.post("/api/auth/setup", json={"password": password}).status_code == 200
    try:
        authorized = client.get("/api/clients", auth=("operator", password))
        assert authorized.status_code == 200
        assert client.get("/api/clients", auth=("operator", "wrong-password")).status_code == 401
    finally:
        with main.db() as session:
            setting = session.get(main.Setting, "password_hash")
            if setting is not None:
                session.delete(setting)
                session.commit()


def test_auth_setup_is_rejected_when_password_already_exists():
    password = f"secret-{uuid4().hex}"
    assert client.post("/api/auth/setup", json={"password": password}).status_code == 200
    try:
        assert client.post("/api/auth/setup", json={"password": password}).status_code == 409
    finally:
        with main.db() as session:
            setting = session.get(main.Setting, "password_hash")
            if setting is not None:
                session.delete(setting)
                session.commit()


def test_school_class_creation_is_idempotent_per_school():
    school_id, _ = _make_school_class()
    with main.db() as session:
        school = session.get(main.School, school_id)
        assert school is not None
        name = school.name
    first = client.post("/api/classes", json={"school_name": name, "class_name": "7В"}).json()
    second = client.post("/api/classes", json={"school_name": name, "class_name": "7В"}).json()
    assert first["class_id"] == second["class_id"]
    assert second["status"] == "existing"


def test_class_creation_rejects_blank_names():
    assert client.post("/api/classes", json={"school_name": "", "class_name": "5А"}).status_code == 422
