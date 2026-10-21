"""Поле ввода сообщения MAX: поиск, вставка текста, проверка и возврат в чат."""

from __future__ import annotations

import logging
import time
import unicodedata
from typing import Any

from .page import (
    CHAT_BACK_ATTEMPTS,
    FIRST_NAME_INPUT_SELECTOR,
    OVERLAY_BACK_SELECTOR,
    _click_back_button,
    _find_back_button,
    _first_visible,
    _first_visible_locator,
    _log_page_state,
)
from .results import MaxBrowserError

log = logging.getLogger("fotomaniabot.max_browser")


CHAT_EDITOR_SELECTORS: list[str] = [
    "div[data-text-entry='true'][contenteditable]",
    "textarea",
    "[contenteditable='true']",
    "[role='textbox']",
    "[data-testid*='message']",
    "[class*='composer'] [contenteditable='true']",
    "[class*='input'] [contenteditable='true']",
]


def _read_editor_text(editor: Any) -> str:
    tag_name = editor.evaluate("(node) => node.tagName.toLowerCase()")
    if tag_name in {"input", "textarea", "select"}:
        return editor.input_value()
    # MAX stores each emoji as <span data-lexical-emoji="🌷"> with an empty placeholder,
    # so innerText/textContent miss it. Read the character from the attribute instead.
    return editor.evaluate(
        "(node) => { const copy = node.cloneNode(true); "
        "copy.querySelectorAll('[data-lexical-emoji]').forEach((el) => el.replaceWith("
        "document.createTextNode(el.getAttribute('data-lexical-emoji') || ''))); "
        "copy.querySelectorAll('img').forEach((img) => img.replaceWith("
        "document.createTextNode(img.alt || ''))); "
        "return (copy.innerText || copy.textContent || '').replace(/\\r\\n/g, '\\n'); }"
    )


_INVISIBLE_EMOJI_PARTS = frozenset(
    {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\ufe0e", "\ufe0f"}
)
_SKIN_TONE_RANGE = ("\U0001f3fb", "\U0001f3ff")


def _comparable_message_text(value: str) -> str:
    """Form of a message used only for the post-insert check.

    Contenteditable editors (MAX) collapse blank lines, strip trailing spaces and may add
    or drop invisible emoji parts (variation selectors, zero-width joiners, skin-tone
    modifiers). All whitespace and those invisible parts are ignored; every visible
    character, emoji included, must match in order.
    """
    text = unicodedata.normalize("NFC", value)
    kept = [
        char
        for char in text
        if not char.isspace()
        and char not in _INVISIBLE_EMOJI_PARTS
        and not (_SKIN_TONE_RANGE[0] <= char <= _SKIN_TONE_RANGE[1])
    ]
    return "".join(kept)


def _mismatch_details(expected: str, actual: str) -> str:
    """Diagnostic for the log: first differing position with the nearby characters."""
    limit = min(len(expected), len(actual))
    index = next((i for i in range(limit) if expected[i] != actual[i]), limit)
    start = max(0, index - 12)
    end = index + 12

    def char_name(text: str) -> str:
        return unicodedata.name(text[index], "UNKNOWN") if index < len(text) else "конец строки"

    return (
        f"позиция={index} "
        f"ожидалось={ascii(expected[start:end])} [{char_name(expected)}] "
        f"получено={ascii(actual[start:end])} [{char_name(actual)}]"
    )


def _insert_and_verify_message(page: Any, editor: Any, message: str) -> str:
    log.info("MAX: очищаю поле сообщения перед вставкой")
    editor.click()
    tag_name = editor.evaluate("(node) => node.tagName.toLowerCase()")
    if tag_name in {"input", "textarea"}:
        log.info("MAX: вставляю текст в поле %s", tag_name)
        editor.fill(message)
    else:
        editor.press("Control+A")
        editor.press("Backspace")
        log.info("MAX: вставляю текст в contenteditable-редактор")
        page.keyboard.insert_text(message)
    deadline = time.monotonic() + 3
    actual = ""
    while time.monotonic() < deadline:
        actual = _read_editor_text(editor)
        if _comparable_message_text(actual) == _comparable_message_text(message):
            log.info("MAX: текст вставлен и проверен")
            return actual
        time.sleep(0.1)
    log.warning(
        "MAX: текст вставлен, но проверка не совпала (ожидалось_символов=%d, "
        "получено_символов=%d) %s",
        len(message),
        len(actual),
        _mismatch_details(_comparable_message_text(message), _comparable_message_text(actual)),
    )
    raise MaxBrowserError("MAX открыл чат, но текст в поле сообщения не совпал с подготовленным.")


def _open_chat_editor(page: Any) -> Any | None:
    """Return the visible message input only when the chat is really in front (no overlay, no contact form)."""
    if _first_visible_locator(page, [page.locator(FIRST_NAME_INPUT_SELECTOR)]) is not None:
        return None
    if _first_visible_locator(page, [page.locator(OVERLAY_BACK_SELECTOR)]) is not None:
        return None
    return _first_visible(page, CHAT_EDITOR_SELECTORS)


def _return_to_chat_after_rename(page: Any) -> None:
    """Leave the contact form with the «назад» arrow until the chat input appears.

    The page is never reloaded. The chat counts as open only when the message input
    is visible and the contact form's first-name field is gone; the input is then clicked.
    """
    log.info("MAX: возвращаюсь в чат кнопкой «назад»")
    clicks = 0
    for _ in range(CHAT_BACK_ATTEMPTS):
        editor = _open_chat_editor(page)
        if editor is not None:
            editor.click()
            log.info("MAX: чат открыт, строка ввода активна (нажатий «назад»: %d)", clicks)
            return
        back = _find_back_button(page)
        if back is None:
            page.wait_for_timeout(300)
            continue
        clicks += 1
        log.info("MAX: нажимаю «назад» (%d из %d)", clicks, CHAT_BACK_ATTEMPTS)
        _click_back_button(back)
        page.wait_for_timeout(700)
    editor = _open_chat_editor(page)
    if editor is not None:
        editor.click()
        log.info("MAX: чат открыт после последнего нажатия «назад» (нажатий: %d)", clicks)
        return
    _log_page_state(page, "rename-back-to-chat-failed")
    raise MaxBrowserError(
        "После переименования не удалось вернуться в чат MAX: строка ввода не открылась."
    )
