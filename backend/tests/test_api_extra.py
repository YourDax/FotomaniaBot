"""Regression tests for the API surface not covered by test_app.py."""

import re
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import session_scope
from app.main import app
from app.models import School

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
    assert (
        client.post("/api/clients", json={"name": "Первый", "chat_link": link}).status_code == 200
    )
    assert (
        client.post("/api/clients", json={"name": "Второй", "chat_link": link}).status_code == 409
    )


def test_duplicate_client_is_detected_by_max_user_id():
    max_user_id = f"max-{uuid4().hex}"
    assert (
        client.post("/api/clients", json={"name": "Первый", "max_user_id": max_user_id}).status_code
        == 200
    )
    assert (
        client.post("/api/clients", json={"name": "Второй", "max_user_id": max_user_id}).status_code
        == 409
    )


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


def test_school_class_creation_is_idempotent_per_school():
    school_id, _ = _make_school_class()
    with session_scope() as session:
        school = session.get(School, school_id)
        assert school is not None
        name = school.name
    first = client.post("/api/classes", json={"school_name": name, "class_name": "7В"}).json()
    second = client.post("/api/classes", json={"school_name": name, "class_name": "7В"}).json()
    assert first["class_id"] == second["class_id"]
    assert second["status"] == "existing"


def test_class_creation_rejects_blank_names():
    assert (
        client.post("/api/classes", json={"school_name": "", "class_name": "5А"}).status_code == 422
    )


# --- Интерфейс оператора -----------------------------------------------------

ASSETS = Path(__file__).resolve().parents[1] / "app" / "static"


def test_web_ui_page_and_assets_are_served():
    page = client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "/static/styles.css" in page.text
    assert '<script type="module" src="/static/js/main.js' in page.text

    css = client.get("/static/styles.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")

    script = client.get("/static/js/main.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.headers["cache-control"] == "no-cache"


def test_web_ui_unknown_asset_is_404():
    assert client.get("/static/unknown.js").status_code == 404
    assert client.get("/static/js/unknown.js").status_code == 404
    assert client.get("/static/js/main.js.map").status_code == 404
    assert client.get("/static/js/..%2Findex.html").status_code in {404, 422}


def test_web_ui_has_no_inline_event_handlers():
    page = client.get("/").text
    assert "onclick=" not in page
    assert "onchange=" not in page


def test_web_ui_calls_only_known_api_routes():
    sources = [path.read_text(encoding="utf-8") for path in sorted((ASSETS / "js").glob("*.js"))]
    source = chr(10).join(sources)
    calls = re.findall(r"fetch\('/api|api\(\s*[`']([^`']+)[`']", source)
    paths = [call for call in calls if call]
    assert paths, "в модулях интерфейса не найдено обращений к API"
    known = {route.path for route in app.routes}
    for call in paths:
        prefix = "/api" + call.split("${")[0]
        assert any(path.startswith(prefix) for path in known), f"неизвестный маршрут: {call}"


def test_every_module_import_resolves_to_an_export():
    """Нет Node для проверки модулей: сверяем import { ... } с export в целевом файле."""
    scripts = {path.name: path.read_text(encoding="utf-8") for path in (ASSETS / "js").glob("*.js")}
    assert "main.js" in scripts
    import_re = re.compile(r"^import \{([^}]*)\} from '\./([\w]+\.js)';", re.M)
    bare_import_re = re.compile(r"^import '\./([\w]+\.js)';", re.M)
    for name, source in scripts.items():
        for names, target in import_re.findall(source):
            assert target in scripts, f"{name}: нет модуля {target}"
            exported = set(
                re.findall(
                    r"^export (?:async function|function|const|class) ([\w$]+)",
                    scripts[target],
                    re.M,
                )
            )
            for item in (part.strip() for part in names.split(",") if part.strip()):
                assert item in exported, f"{name}: {item} не экспортируется из {target}"
        for target in bare_import_re.findall(source):
            assert target in scripts, f"{name}: нет модуля {target}"


def test_ui_modules_are_served_with_javascript_mime_type():
    for path in (ASSETS / "js").glob("*.js"):
        response = client.get(f"/static/js/{path.name}")
        assert response.status_code == 200, path.name
        assert response.headers["content-type"].startswith("text/javascript")
