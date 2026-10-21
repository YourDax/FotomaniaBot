"""Наборы сообщений рассылки: несколько текстов на роль и по ним — на получателя.

Рассылка хранит списки текстов для КР и РК (`messages_kr`, `messages_rk`), а
задание — список подготовленных для конкретного получателя сообщений
(`messages`) с отметкой подготовки в MAX у каждого. Поля `message_kr`,
`message_rk`, `rendered_message` и `browser_prepared_at` остаются зеркалом
первого сообщения для совместимости со старыми данными и отчётами.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

MAX_MESSAGES_PER_ROLE = 5
MAX_MESSAGE_LENGTH = 4000


def _load_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return value if isinstance(value, list) else []


def own_messages(campaign: Any, role: str) -> list[str]:
    """Тексты, заданные в рассылке именно для этой роли (без подстановки чужих)."""
    column, legacy = ("messages_rk", "message_rk") if role == "RK" else ("messages_kr", "message_kr")
    items = [str(item) for item in _load_list(getattr(campaign, column, None)) if str(item).strip()]
    if items:
        return items
    single = getattr(campaign, legacy, None)
    return [single] if single and single.strip() else []


def campaign_messages(campaign: Any, role: str) -> list[str]:
    """Тексты для роли; если для неё ничего не задано, берутся тексты другой роли."""
    other = "KR" if role == "RK" else "RK"
    items = own_messages(campaign, role) or own_messages(campaign, other)
    if items:
        return items
    generic = getattr(campaign, "message", "") or ""
    return [generic] if generic.strip() else []


def dump_messages(values: list[str]) -> str | None:
    return json.dumps(values, ensure_ascii=False) if values else None


def clean_messages(values: list[str] | None) -> list[str]:
    """Обрезает пробелы; пустое сообщение внутри набора недопустимо."""
    cleaned = [(value or "").strip() for value in (values or [])]
    if any(not value for value in cleaned):
        raise ValueError("Заполните текст каждого сообщения или уменьшите их количество")
    if len(cleaned) > MAX_MESSAGES_PER_ROLE:
        raise ValueError(f"Сообщений на роль не больше {MAX_MESSAGES_PER_ROLE}")
    return cleaned


def task_messages(task: Any) -> list[dict[str, Any]]:
    """Сообщения задания: [{"text", "prepared_at"}]; для старых заданий — одно."""
    items: list[dict[str, Any]] = []
    for entry in _load_list(getattr(task, "messages", None)):
        if isinstance(entry, dict) and isinstance(entry.get("text"), str):
            items.append({"text": entry["text"], "prepared_at": entry.get("prepared_at")})
    if items:
        return items
    if (task.rendered_message or "").strip():
        prepared = task.browser_prepared_at
        return [{"text": task.rendered_message, "prepared_at": prepared.isoformat() if prepared else None}]
    return []


def save_task_messages(task: Any, items: list[dict[str, Any]]) -> None:
    """Записывает сообщения и обновляет зеркальные поля первого сообщения."""
    task.messages = json.dumps(items, ensure_ascii=False)
    task.rendered_message = items[0]["text"] if items else ""
    stamps = [datetime.fromisoformat(item["prepared_at"]) for item in items if item.get("prepared_at")]
    task.browser_prepared_at = max(stamps) if stamps else None


def rebuild_task_messages(task: Any, texts: list[str]) -> bool:
    """Подставляет новые тексты, сохраняя отметку подготовки у неизменённых. True, если что-то изменилось."""
    old = task_messages(task)
    items = [
        {
            "text": text,
            "prepared_at": old[i]["prepared_at"] if i < len(old) and old[i]["text"] == text else None,
        }
        for i, text in enumerate(texts)
    ]
    if items == old:
        return False
    save_task_messages(task, items)
    return True
