"""Переименование контакта в MAX: имя по шаблону, фамилия очищается."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from .connection import cdp_url, get_session
from .editor import CHAT_EDITOR_SELECTORS, _return_to_chat_after_rename
from .page import _first_visible, _first_visible_locator, _log_page_state, _return_to_main_screen
from .results import MaxBrowserError, RenameResult
from .search import (
    _dismiss_phone_not_found_popup,
    _max_phone_digits,
    _open_phone_search,
    _phone_not_found_popup_text,
)

log = logging.getLogger("fotomaniabot.max_browser")


def _open_chat_for_rename(page: Any, phone: str) -> None:
    _return_to_main_screen(page)
    search = _open_phone_search(page)
    digits = _max_phone_digits(phone)
    if not digits:
        raise MaxBrowserError("Номер телефона клиента не содержит цифр.")
    search.fill("")
    search.fill(digits)
    search.press("Enter")
    log.info("MAX: номер отправлен для поиска контакта, ожидаю открытие чата")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _phone_not_found_popup_text(page):
            log.warning("MAX: контакт не найден, переименование невозможно")
            _log_page_state(page, "rename-contact-not-found")
            _dismiss_phone_not_found_popup(page)
            raise MaxBrowserError("Контакт не найден в MAX по указанному номеру телефона.")
        if _first_visible(page, CHAT_EDITOR_SELECTORS) is not None:
            log.info("MAX: чат открыт для переименования контакта")
            return
        page.wait_for_timeout(250)
    _log_page_state(page, "rename-chat-not-opened")
    raise MaxBrowserError("После поиска по номеру не удалось открыть чат в MAX.")


def _open_profile_editor(page: Any) -> tuple[Any, bool]:
    """Open the contact form. Returns (first_name_input, add_mode).

    add_mode is True for «В контакты» (new contact, needs «Сохранить»);
    False for «Редактировать» (existing contact, no save button).
    """
    avatar = _first_visible_locator(page, [page.locator("button[aria-label^='Открыть профиль']")])
    if avatar is None:
        _log_page_state(page, "rename-avatar-not-found")
        raise MaxBrowserError("В открытом чате не найден аватар для открытия профиля.")
    log.info("MAX: открываю профиль клиента")
    avatar.click()
    page.wait_for_timeout(500)
    add_button = _first_visible_locator(
        page, [page.get_by_role("button", name=re.compile(r"В контакты"))]
    )
    add_mode = add_button is not None
    if add_button is not None:
        log.info("MAX: найдена кнопка «В контакты», добавляю контакт")
        add_button.click()
    else:
        edit_button = _first_visible_locator(
            page,
            [
                page.get_by_role("button", name=re.compile(r"Редактировать")),
                page.locator("button[aria-label='Показать настройки']"),
            ],
        )
        if edit_button is None:
            _log_page_state(page, "rename-edit-button-not-found")
            raise MaxBrowserError(
                "В профиле клиента не найдена кнопка «В контакты» или редактирования."
            )
        log.info("MAX: открываю редактирование контакта")
        edit_button.click()
    first_name_input = page.locator("input[name='firstName']").first
    first_name_input.wait_for(state="visible", timeout=10000)
    return first_name_input, add_mode


def _save_contact_name(page: Any, first_name_input: Any, first_name: str, add_mode: bool) -> bool:
    """Apply the new name. Returns False when MAX shows no «Сохранить» (name already correct)."""
    last_name_input = _first_visible_locator(page, [page.locator("input[name='lastName']")])
    if last_name_input is None:
        _log_page_state(page, "rename-last-name-not-found")
        raise MaxBrowserError("В форме контакта не найдено поле «Фамилия».")
    first_name_input.fill(first_name)
    last_name_input.fill("")
    if first_name_input.input_value() != first_name or last_name_input.input_value() != "":
        raise MaxBrowserError("MAX не принял введённые имя и фамилию. Изменения не сохранены.")
    page.wait_for_timeout(600)
    save_button = _first_visible_locator(
        page,
        [
            page.get_by_role("button", name=re.compile(r"^\s*(Сохранить|Готово)\s*$")),
            page.locator("button[aria-label='Сохранить']"),
        ],
    )
    if save_button is None:
        if add_mode:
            _log_page_state(page, "rename-save-button-not-found")
            raise MaxBrowserError("В форме нового контакта не появилась кнопка «Сохранить».")
        log.info("MAX: «Сохранить» не появилось, имя контакта уже корректно")
        return False
    log.info("MAX: сохраняю новое имя контакта")
    save_button.click()
    page.wait_for_timeout(800)
    return True


def rename_contact(client_name: str, identity: str, first_name: str) -> RenameResult:
    """Rename a MAX contact found by phone. Never sends or edits chat messages."""
    log.info("MAX rename.start cdp_url=%s client=%s", cdp_url(), client_name)

    def job(page: Any) -> RenameResult:
        _open_chat_for_rename(page, identity)
        first_name_input, add_mode = _open_profile_editor(page)
        changed = _save_contact_name(page, first_name_input, first_name, add_mode)
        _return_to_chat_after_rename(page)
        status = "CONTACT_RENAMED" if changed else "ALREADY_CORRECT"
        log.info("MAX: переименование для %s, статус=%s", client_name, status)
        return RenameResult(
            status=status,
            page_url=page.url,
            client_name=client_name,
            first_name=first_name,
        )

    return get_session().run(
        job,
        label=f"rename client={client_name}",
        timeout_message="MAX не успел отобразить форму контакта. Повторите переименование вручную.",
        unexpected_message=(
            "Ошибка автоматизации MAX при переименовании. "
            "Подробности записаны в журнале backend."
        ),
    )
