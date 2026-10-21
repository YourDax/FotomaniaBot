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


ROLE_PREFIXES: dict[str, str] = {"KR": "КР", "RK": "РК"}
CONTACT_NAME_MAX_LENGTH = 64
PATRONYMIC_SUFFIXES: tuple[str, ...] = ("вна", "вич", "ична", "ич")


def contact_first_name(role: str, school: str, class_name: str, full_name: str, year: int) -> str:
    """Build the MAX contact first name ``РК|КР Школа Класс - Год Имя Отчество``.

    The surname (first word of ФИО) is dropped here; the surname field itself
    is cleared separately by the browser automation.
    """
    prefix = ROLE_PREFIXES.get(role)
    if prefix is None:
        raise ValueError(f"Неизвестная роль получателя: {role}")
    school_part = " ".join(school.split())
    class_part = " ".join(class_name.split())
    if not school_part or not class_part:
        raise ValueError("Для переименования контакта нужны школа и класс")
    words = full_name.split()
    if len(words) >= 3:
        given = " ".join(words[1:])
    elif len(words) == 2 and words[1].casefold().endswith(PATRONYMIC_SUFFIXES):
        given = " ".join(words)
    elif len(words) == 2:
        given = words[1]
    else:
        given = " ".join(words)
    if not given:
        raise ValueError("В ФИО клиента нет имени для переименования")
    result = f"{prefix} {school_part} {class_part} - {year} {given}"
    if len(result) > CONTACT_NAME_MAX_LENGTH:
        raise ValueError(
            f"Имя контакта длиннее {CONTACT_NAME_MAX_LENGTH} символов: "
            "сократите название школы или ФИО"
        )
    return result
