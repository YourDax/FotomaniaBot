"""Regression tests: saved campaign texts per role and editing of created campaigns."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _make_client(role: str = "KR") -> int:
    response = client.post(
        "/api/clients",
        json={"name": f"Иванов Иван {uuid4().hex[:6]}", "phone": None, "role": role},
    )
    assert response.status_code == 200
    return response.json()["id"]


def _create_campaign(message_kr: str | None, message_rk: str | None, client_ids: list[int]) -> dict:
    response = client.post(
        "/api/campaigns",
        json={
            "name": f"Тест {uuid4().hex[:6]}",
            "message": message_kr or message_rk or "",
            "message_kr": message_kr,
            "message_rk": message_rk,
            "client_ids": client_ids,
        },
    )
    assert response.status_code == 200
    return response.json()


def _template_bodies(role: str) -> list[str]:
    return [item["body"] for item in client.get(f"/api/message-templates/{role}").json()]


def test_created_campaign_saves_texts_per_role_without_duplicates():
    body_kr = f"КР {uuid4().hex} {{name}}"
    body_rk = f"РК {uuid4().hex} {{name}}"
    kr_id = _make_client("KR")
    rk_id = _make_client("RK")
    _create_campaign(body_kr, body_rk, [kr_id, rk_id])
    _create_campaign(body_kr, body_rk, [kr_id])
    assert _template_bodies("KR").count(body_kr) == 1
    assert body_rk not in _template_bodies("KR")
    assert _template_bodies("RK").count(body_rk) == 1
    assert body_kr not in _template_bodies("RK")


def test_message_templates_reject_unknown_role():
    assert client.get("/api/message-templates/XX").status_code == 400


def test_bulk_edit_updates_only_unprocessed_tasks_and_saves_template():
    kr_id = _make_client("KR")
    rk_id = _make_client("RK")
    campaign = _create_campaign("Старый КР {name}", "Старый РК {name}", [kr_id, rk_id])
    tasks = client.get(f"/api/campaigns/{campaign['id']}/tasks").json()
    kr_task = next(task for task in tasks if task["recipient_role"] == "KR")
    rk_task = next(task for task in tasks if task["recipient_role"] == "RK")
    assert client.patch(
        f"/api/tasks/{rk_task['id']}/status", json={"status": "SENT"}
    ).status_code == 200

    new_kr = f"Новый КР {uuid4().hex} {{name}}"
    response = client.patch(
        f"/api/campaigns/{campaign['id']}/messages",
        json={"message_kr": new_kr, "message_rk": "Новый РК {name}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["updated"] == 1
    assert body["skipped"] == 1
    assert body["campaign"]["message_kr"] == new_kr

    tasks_after = {t["id"]: t for t in client.get(f"/api/campaigns/{campaign['id']}/tasks").json()}
    assert tasks_after[kr_task["id"]]["message"].startswith("Новый КР")
    assert "Старый РК" in tasks_after[rk_task["id"]]["message"]
    assert new_kr in _template_bodies("KR")


def test_bulk_edit_requires_at_least_one_text_and_known_campaign():
    campaign = _create_campaign("КР {name}", None, [_make_client("KR")])
    empty = client.patch(
        f"/api/campaigns/{campaign['id']}/messages", json={"message_kr": "  ", "message_rk": None}
    )
    assert empty.status_code == 422
    missing = client.patch("/api/campaigns/999999/messages", json={"message_kr": "Текст {name}"})
    assert missing.status_code == 404


def test_single_task_message_edit_resets_prepared_draft_and_checks_status():
    campaign = _create_campaign("КР {name}", None, [_make_client("KR")])
    task = client.get(f"/api/campaigns/{campaign['id']}/tasks").json()[0]
    response = client.patch(
        f"/api/tasks/{task['id']}/message", json={"message": "Персональный текст"}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Персональный текст"

    client.patch(f"/api/tasks/{task['id']}/status", json={"status": "SENT"})
    locked = client.patch(f"/api/tasks/{task['id']}/message", json={"message": "Ещё одна правка"})
    assert locked.status_code == 409


def test_single_task_message_rejects_blank_text():
    campaign = _create_campaign("КР {name}", None, [_make_client("KR")])
    task = client.get(f"/api/campaigns/{campaign['id']}/tasks").json()[0]
    response = client.patch(f"/api/tasks/{task['id']}/message", json={"message": "   "})
    assert response.status_code == 422
