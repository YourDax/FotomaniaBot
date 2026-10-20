"""Прикладные функции без зависимости от FastAPI.

Здесь живут чистые преобразования (рендер сообщения, CSV-экранирование,
эвристика заголовков, сериализация клиента), чтобы `main.py` оставался
тонким слоем маршрутов.
"""

from __future__ import annotations

import json
from typing import Any

from .models import Client

HEADER_KEYWORDS: tuple[str, ...] = (
    "класс",
    "фиокр",
    "телефонкр",
    "фиорк",
    "телефонрк",
    "фио",
    "телефон",
)

CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@")


def render_message(template: str, client: Client) -> str:
    """Substitute ``{name}`` and custom fields into a campaign template."""
    try:
        custom = json.loads(client.custom_fields or "{}")
    except (ValueError, TypeError):
        custom = {}
    fields = {"name": client.name, **custom}
    result = template
    for key, value in fields.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def csv_safe(value: Any) -> str:
    """Neutralise spreadsheet formula injection for exported CSV cells."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in CSV_DANGEROUS_PREFIXES else text


def normalized_header(value: Any) -> str:
    return "".join(str(value or "").lower().replace("ё", "е").split())


def header_score(row: list[Any]) -> int:
    text = " ".join(normalized_header(value) for value in row)
    return sum(keyword in text for keyword in HEADER_KEYWORDS)


def detect_header_row(rows: list[list[Any]]) -> int:
    candidates = [(header_score(row), index) for index, row in enumerate(rows[:30])]
    score, index = max(candidates, default=(0, 0))
    return 0 if score == 0 else index


def client_dict(client: Client) -> dict[str, Any]:
    fields = (
        "id",
        "name",
        "phone",
        "max_user_id",
        "username",
        "chat_link",
        "source",
        "consent_basis",
        "opted_out",
        "school_id",
        "class_id",
        "role",
        "created_at",
        "updated_at",
    )
    try:
        custom = json.loads(client.custom_fields or "{}")
    except (ValueError, TypeError):
        custom = {}
    return {**{key: getattr(client, key) for key in fields}, "custom_fields": custom}
