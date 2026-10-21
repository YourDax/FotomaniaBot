"""Работа с уже авторизованной вкладкой MAX через CDP (Playwright).

Модуль никогда не нажимает кнопку отправки. Публичный интерфейс: `prepare_message`,
`open_chat`, `rename_contact`, `shutdown` и результаты операций.
"""

from __future__ import annotations

from .chat import (
    _PROFILE_BUTTON_PREFIX,
    _open_chat_is_for_contact,
    normalize_contact_name,
    open_chat,
    prepare_message,
)
from .connection import shutdown, status
from .editor import _return_to_chat_after_rename
from .page import (
    CHAT_BACK_ATTEMPTS,
    CHAT_BACK_SELECTOR,
    FIRST_NAME_INPUT_SELECTOR,
    OVERLAY_BACK_SELECTOR,
)
from .rename import rename_contact
from .results import MaxBrowserError, PreparationResult, RenameResult
from .search import _is_phone_not_found_text, _max_phone_digits

__all__ = [
    "CHAT_BACK_ATTEMPTS",
    "CHAT_BACK_SELECTOR",
    "FIRST_NAME_INPUT_SELECTOR",
    "OVERLAY_BACK_SELECTOR",
    "MaxBrowserError",
    "PreparationResult",
    "RenameResult",
    "_PROFILE_BUTTON_PREFIX",
    "_is_phone_not_found_text",
    "_max_phone_digits",
    "_open_chat_is_for_contact",
    "_return_to_chat_after_rename",
    "normalize_contact_name",
    "open_chat",
    "prepare_message",
    "rename_contact",
    "shutdown",
    "status",
]
