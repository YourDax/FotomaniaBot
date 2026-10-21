"""Поиск контакта по номеру телефона в MAX и распознавание «контакт не найден»."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from ..phones import phone_digits
from .page import _first_visible, _first_visible_locator, _log_page_state
from .results import MaxBrowserError

log = logging.getLogger("fotomaniabot.max_browser")


def _max_phone_digits(value: str) -> str:
    return phone_digits(value)


def _open_phone_search(page: Any) -> Any:
    log.info("MAX: ожидаю кнопку «+» для поиска контакта")
    page.wait_for_timeout(500)
    plus = _first_visible_locator(
        page,
        [
            page.get_by_role("button", name="Начать общение"),
            page.get_by_role("button", name=re.compile(r"^\s*\+\s*$")),
            page.get_by_role("button", name=re.compile(r"(добавить|add)", re.IGNORECASE)),
            page.locator("button[aria-label*='Добавить'], button[title*='Добавить']"),
            page.locator("button:has(svg path[d^='M26 0'])"),
            page.locator("path[d^='M26 0']"),
            page.locator("svg:has(path[d^='M26 0'])"),
            page.locator("svg path[d^='M26 0']").locator(
                "xpath=ancestor::*[@role='button' or self::button or @tabindex='0'][1]"
            ),
            page.locator("svg path[d^='M26 0']").locator("xpath=.."),
            page.locator("[class*='button']:has(svg path[d^='M26 0'])"),
        ],
    )
    if plus is None:
        _log_page_state(page, "plus-not-found")
        raise MaxBrowserError(
            "Не найдена кнопка «+» рядом с поиском MAX. Откройте основной экран MAX."
        )
    log.info("MAX: кнопка «+» найдена, открываю меню поиска")
    plus.click()
    phone_locators = [
        page.get_by_text("Найти по номеру", exact=True),
        page.get_by_text(re.compile(r"найти\s+по\s+номеру", re.IGNORECASE)),
        page.get_by_text(re.compile(r"поиск\s+по\s+номеру", re.IGNORECASE)),
        page.get_by_text(re.compile(r"номер\s+телефона", re.IGNORECASE)),
    ]
    phone_search = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        phone_search = _first_visible_locator(page, phone_locators)
        if phone_search is not None:
            break
        page.wait_for_timeout(250)
    if phone_search is None:
        try:
            log.info("MAX menu body after plus: %s", page.locator("body").inner_text()[:3000])
        except Exception:
            log.exception("MAX menu body logging failed")
        _log_page_state(page, "phone-menu-not-found")
        raise MaxBrowserError("В меню MAX не найден пункт «Найти по номеру».")
    log.info("MAX: пункт «Найти по номеру» найден, открываю поле телефона")
    phone_search.click()
    search = _first_visible(
        page,
        [
            "input.field[inputmode='decimal'][autocomplete='tel']",
            "input[type='text'][inputmode='decimal'][autocomplete='tel']",
            "input.field[autocomplete='tel']",
            "input[placeholder*='номер']",
            "input[aria-label*='номер']",
            "input[type='tel']",
            "input[placeholder*='телефон']",
            "input[aria-label*='телефон']",
            "input:not([type='search']):not([type='hidden'])",
        ],
    )
    if search is None:
        _log_page_state(page, "phone-input-not-found")
        raise MaxBrowserError("После выбора «Найти по номеру» не найдено поле номера телефона.")
    log.info("MAX: поле телефона найдено")
    return search


def _is_phone_not_found_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.replace("\u2011", "-")).strip()
    return bool(
        re.search(
            r"(не\s+нашли\s+номер|"
            r"(номер|контакт|пользователь|собеседник).{0,60}не\s+найден|"
            r"не\s+удалось\s+найти|"
            r"ничего\s+не\s+найдено|"
            r"отправьте\s+ссылку\s*-\s*приглашени)",
            normalized,
            re.IGNORECASE,
        )
    )


def _phone_not_found_popup_text(page: Any) -> str | None:
    containers = page.locator(
        "[role='dialog'], [role='alertdialog'], .popoverPortal, "
        "[role='alert'], [aria-live], [class*='modal'], [class*='dialog'], "
        "[class*='popup'], [class*='toast']"
    )
    try:
        count = min(containers.count(), 30)
    except Exception:
        count = 0
    for index in range(count):
        candidate = containers.nth(index)
        try:
            if not candidate.is_visible(timeout=200):
                continue
            text = candidate.inner_text(timeout=200).strip()
        except Exception:
            continue
        if _is_phone_not_found_text(text):
            return re.sub(r"\s+", " ", text)[:400]
    try:
        body_text = page.locator("body").inner_text(timeout=200)
    except Exception:
        return None
    if _is_phone_not_found_text(body_text):
        return re.sub(r"\s+", " ", body_text)[:400]
    return None


def _dismiss_phone_not_found_popup(page: Any) -> None:
    log.info("MAX: закрываю уведомление о ненайденном контакте")
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        page.mouse.click(8, 8)
        page.wait_for_timeout(250)
        if _phone_not_found_popup_text(page):
            log.warning("MAX: уведомление не исчезло, обновляю страницу")
            page.reload(wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1000)
        else:
            log.info("MAX: уведомление о ненайденном контакте закрыто")
    except Exception:
        log.exception("MAX: не удалось закрыть уведомление о ненайденном контакте")
