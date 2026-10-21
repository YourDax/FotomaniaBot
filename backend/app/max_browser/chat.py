"""Подготовка черновика в открытом чате MAX и открытие чата по номеру телефона."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from .connection import cdp_url, get_session
from .editor import (
    _insert_and_verify_message,
    _open_chat_editor,
    _return_to_chat_after_rename,
)
from .page import (
    OVERLAY_BACK_SELECTOR,
    _first_visible,
    _first_visible_locator,
    _log_page_state,
    _return_to_main_screen,
)
from .results import MaxBrowserError, PreparationResult
from .search import (
    _dismiss_phone_not_found_popup,
    _max_phone_digits,
    _open_phone_search,
    _phone_not_found_popup_text,
)

log = logging.getLogger("fotomaniabot.max_browser")

_NAME_SPACE_CHARS = re.compile(r"[\s\u00a0\u200b\u200c\u200d\u2060\ufeff]+")
_NAME_DASHES = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2212]")
_CHAT_HEADER_TITLE_SELECTORS: list[str] = [
    # Разметка шапки открытого чата: span.title > span.name > span.text внутри content--subtitle.
    "div[class*='content--subtitle'] span.title span.name span.text",
    "span.title span.name span.text",
    "[class*='header'] h2[class*='title']",
    "[class*='header'] [class*='title'] [class*='name']",
    "[class*='header'] button[aria-label^='Открыть профиль'] [class*='name']",
    "[class*='header'] button[aria-label^='Открыть профиль'] [class*='title']",
]
_PROFILE_BUTTON_PREFIX = "Открыть профиль "


def normalize_contact_name(value: str) -> str:
    """Comparable form of a contact name: case, «ё», dashes and whitespace are ignored."""
    text = _NAME_DASHES.sub("-", value.replace("\u00a0", " "))
    text = _NAME_SPACE_CHARS.sub(" ", text).strip().casefold()
    return text.replace("ё", "е")


def _read_open_chat_title(page: Any) -> str | None:
    """Return the contact name shown in the open chat header, or None when it is unknown.

    Only the header title is read. Status lines («Был(-а) недавно», «В сети») are never
    part of it, and a truncated title (ends with «…») is treated as unknown.
    """
    for selector in _CHAT_HEADER_TITLE_SELECTORS:
        locator = page.locator(selector)
        try:
            count = min(locator.count(), 5)
        except Exception:
            continue
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible(timeout=200):
                    continue
                text = candidate.inner_text(timeout=300)
            except Exception:
                continue
            text = _NAME_SPACE_CHARS.sub(" ", text).strip()
            if text and not text.endswith(("...", "…")):
                return text
    try:
        profile_buttons = page.locator("button[aria-label^='Открыть профиль']")
        if profile_buttons.count() > 0:
            label = profile_buttons.first.get_attribute("aria-label", timeout=300) or ""
            if label.startswith(_PROFILE_BUTTON_PREFIX):
                title = label[len(_PROFILE_BUTTON_PREFIX) :].strip()
                if title and not title.endswith(("...", "…")):
                    return title
    except Exception:
        log.info("MAX: не удалось прочитать имя из кнопки профиля в шапке")
    return None


def _open_chat_is_for_contact(page: Any, expected_name: str | None) -> bool:
    """True only when the chat already open is exactly the contact we need.

    Any failure (no header, changed markup, empty or truncated title, page error)
    means «не совпало»: the caller then falls back to the phone search.
    """
    if not expected_name or not normalize_contact_name(expected_name):
        return False
    try:
        title = _read_open_chat_title(page)
    except Exception:
        log.exception("MAX: ошибка чтения шапки чата, ищу контакт по номеру")
        return False
    if title is None:
        log.info("MAX: имя в шапке открытого чата не определено, ищу контакт по номеру")
        return False
    matched = normalize_contact_name(title) == normalize_contact_name(expected_name)
    log.info("MAX: открытый чат «%s», ожидается «%s», совпадение=%s", title, expected_name, matched)
    return matched


# Контакт, который только что открыт поиском по номеру: цифры номера и имя в шапке чата.
# Имя в MAX может не совпадать с шаблоном (контакт ещё не переименован), но человека уже
# подтвердил поиск по номеру, поэтому следующие сообщения ему не требуют нового поиска.
_last_search: dict[str, str] = {}


def _remember_searched_chat(page: Any, phone_digits: str) -> None:
    try:
        title = _read_open_chat_title(page)
    except Exception:
        title = None
    _last_search.clear()
    if title and phone_digits:
        _last_search.update(digits=phone_digits, title=normalize_contact_name(title))


def _open_chat_is_last_searched(page: Any, phone_digits: str) -> bool:
    """True, если открыт тот же чат (то же имя в шапке), что дал последний поиск по этому номеру."""
    if not phone_digits or _last_search.get("digits") != phone_digits:
        return False
    try:
        title = _read_open_chat_title(page)
    except Exception:
        return False
    matched = title is not None and normalize_contact_name(title) == _last_search["title"]
    log.info("MAX: чат последнего поиска по этому номеру открыт: %s", matched)
    return matched


def _prepare_draft_in_open_chat(
    page: Any, client_name: str, message: str | None
) -> PreparationResult | None:
    """Use the chat that is already open. Returns None when the editor is not reachable."""
    if _first_visible_locator(page, [page.locator(OVERLAY_BACK_SELECTOR)]) is not None:
        log.info("MAX: поверх чата открыт оверлей, закрываю его перед вставкой")
        try:
            _return_to_chat_after_rename(page)
        except MaxBrowserError:
            return None
    editor = _open_chat_editor(page)
    if editor is None:
        return None
    if message is None:
        return PreparationResult(
            status="CHAT_OPENED", page_url=page.url, client_name=client_name, verified_text=""
        )
    actual = _insert_and_verify_message(page, editor, message)
    return PreparationResult(
        status="DRAFT_PREPARED", page_url=page.url, client_name=client_name, verified_text=actual
    )


def _prepare_on_page(
    page: Any,
    client_name: str,
    identity: str,
    message: str | None,
    expected_name: str | None,
) -> PreparationResult:
    editor_selectors = [
        "textarea",
        "[contenteditable='true']",
        "[role='textbox']",
        "[data-testid*='message']",
        "[class*='composer'] [contenteditable='true']",
        "[class*='input'] [contenteditable='true']",
    ]
    phone_digits = _max_phone_digits(identity)
    if _open_chat_is_for_contact(page, expected_name) or _open_chat_is_last_searched(
        page, phone_digits
    ):
        prepared = _prepare_draft_in_open_chat(page, client_name, message)
        if prepared is not None:
            log.info("MAX: черновик подготовлен в уже открытом чате, поиск по номеру не нужен")
            return prepared
    _return_to_main_screen(page)
    search = _open_phone_search(page)
    if not phone_digits:
        raise MaxBrowserError("Номер телефона клиента не содержит цифр.")
    log.info(
        "MAX: ввожу номер для поиска (цифр после нормализации: %d)",
        len(phone_digits),
    )
    search.fill("")
    search.fill(phone_digits)
    search.press("Enter")
    log.info("MAX: номер отправлен, ожидаю открытие чата")
    editor = None
    editor_deadline = time.monotonic() + 10
    while time.monotonic() < editor_deadline:
        popup_text = _phone_not_found_popup_text(page)
        if popup_text:
            log.warning("MAX: контакт не найден, прекращаю сценарий")
            _log_page_state(page, "phone-contact-not-found")
            _dismiss_phone_not_found_popup(page)
            raise MaxBrowserError("Контакт не найден в MAX по указанному номеру телефона.")
        editor = _first_visible(page, editor_selectors)
        if editor is not None:
            break
        page.wait_for_timeout(250)
    if editor is None:
        log.warning("MAX: чат или поле сообщения не открылись за 10 секунд")
        _log_page_state(page, "chat-not-opened-or-editor-not-found")
        raise MaxBrowserError(
            "После поиска по номеру не удалось открыть чат или найти поле ввода сообщения MAX."
        )
    log.info("MAX: чат открыт, поле сообщения найдено")
    _remember_searched_chat(page, phone_digits)
    if message is None:
        log.info("MAX: чат открыт без вставки текста")
        return PreparationResult(
            status="CHAT_OPENED",
            page_url=page.url,
            client_name=client_name,
            verified_text="",
        )
    actual = _insert_and_verify_message(page, editor, message)
    log.info("MAX: черновик подготовлен для %s; отправка не выполнялась", client_name)
    return PreparationResult(
        status="DRAFT_PREPARED",
        page_url=page.url,
        client_name=client_name,
        verified_text=actual,
    )


def prepare_message(
    client_name: str,
    identity: str,
    message: str | None,
    expected_name: str | None = None,
) -> PreparationResult:
    """Open a matching MAX chat and put a verified draft in its editor.

    This deliberately never invokes the send control. The browser must already
    be running with remote debugging enabled and an authenticated MAX tab.
    """
    log.info("MAX session.start cdp_url=%s client=%s", cdp_url(), client_name)
    return get_session().run(
        lambda page: _prepare_on_page(page, client_name, identity, message, expected_name),
        label=f"preparation client={client_name}",
        timeout_message=(
            "MAX не успел отобразить нужный элемент. "
            "Проверьте загрузку вкладки и повторите вручную."
        ),
        unexpected_message=(
            "Ошибка автоматизации MAX. Подробности записаны в журнал session.log "
            "(папка logs в каталоге данных)."
        ),
    )


def open_chat(
    client_name: str, identity: str, expected_name: str | None = None
) -> PreparationResult:
    return prepare_message(client_name, identity, None, expected_name=expected_name)
