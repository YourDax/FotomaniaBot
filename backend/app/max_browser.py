from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .phones import phone_digits

log = logging.getLogger("fotomaniabot.max_browser")


@dataclass
class PreparationResult:
    status: str
    page_url: str
    client_name: str
    verified_text: str


class MaxBrowserError(RuntimeError):
    pass


def _max_phone_digits(value: str) -> str:
    return phone_digits(value)


def _first_visible(page: Any, selectors: list[str]) -> Any | None:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            log.info("MAX: страница изменилась при поиске элемента %s", selector)
            continue
        for index in range(min(count, 5)):
            candidate = locator.nth(index)
            try:
                if (
                    candidate.is_visible(timeout=300)
                    and candidate.is_editable(timeout=300)
                ):
                    return candidate
            except Exception:
                continue
    return None


def _first_visible_locator(page: Any, locators: list[Any]) -> Any | None:
    for locator in locators:
        for index in range(min(locator.count(), 10)):
            candidate = locator.nth(index)
            if candidate.is_visible():
                return candidate
    return None


def _page_has_controls(page: Any) -> bool:
    try:
        return page.locator("button, [role='button'], input").count() > 0
    except Exception:
        log.info("MAX page changed during readiness check url=%s", page.url)
        return False


def _return_to_main_screen(page: Any) -> None:
    back = _first_visible_locator(
        page,
        [
            page.get_by_role("button", name="Перейти назад"),
            page.locator("button[aria-label*='назад' i]"),
        ],
    )
    if back is None:
        log.info("MAX: основной экран уже открыт, возврат не требуется")
        return
    log.info("MAX: ожидаю возврат на основной экран перед поиском")
    back.click()
    page.wait_for_timeout(500)
    log.info("MAX: основной экран открыт")


def _log_page_state(page: Any, stage: str) -> None:
    try:
        buttons = page.locator("button, [role='button']")
        button_data = []
        for index in range(min(buttons.count(), 80)):
            item = buttons.nth(index)
            if item.is_visible():
                button_data.append(item.evaluate(
                    "(node) => ({text: node.innerText, aria: node.getAttribute('aria-label'), "
                    "title: node.getAttribute('title'), html: node.outerHTML.slice(0, 500)})"
                ))
        inputs = page.locator("input")
        input_data = []
        for index in range(min(inputs.count(), 40)):
            item = inputs.nth(index)
            if item.is_visible():
                input_data.append(item.evaluate(
                    "(node) => ({type: node.type, placeholder: node.placeholder, "
                    "autocomplete: node.autocomplete, inputmode: node.inputMode, className: node.className})"
                ))
        log.info(
            "MAX DOM stage=%s url=%s title=%s buttons=%s inputs=%s",
            stage,
            page.url,
            page.title(),
            button_data,
            input_data,
        )
        if os.getenv("MAX_SAVE_DOM_LOG", "0") == "1":
            log_dir = Path(__file__).resolve().parents[1] / "logs"
            log_dir.mkdir(exist_ok=True)
            snapshot = log_dir / f"max-{int(time.time())}-{stage}.html"
            snapshot.write_text(page.content(), encoding="utf-8")
            log.info("MAX DOM snapshot saved path=%s", snapshot)
    except Exception:
        log.exception("MAX DOM logging failed stage=%s", stage)


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
        raise MaxBrowserError(
            "В меню MAX не найден пункт «Найти по номеру»."
        )
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
        raise MaxBrowserError(
            "После выбора «Найти по номеру» не найдено поле номера телефона."
        )
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


def _ensure_cdp_endpoint(playwright: Any, cdp_url: str) -> None:
    """Start a persistent, non-authenticating Chromium when CDP is absent."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=1):
            return
    except Exception:
        pass

    port = cdp_url.rsplit(":", 1)[-1].rstrip("/")
    configured_profile = os.getenv("MAX_BROWSER_PROFILE_DIR")
    profile = Path(configured_profile) if configured_profile else (
        Path(__file__).resolve().parents[2] / ".max-browser-profile"
    )
    if not profile.is_absolute():
        profile = Path(__file__).resolve().parents[2] / profile
    profile = profile.resolve()
    profile.mkdir(parents=True, exist_ok=True)
    executable = playwright.chromium.executable_path
    try:
        subprocess.Popen(
            [
                executable,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "https://web.max.ru/",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise MaxBrowserError(
            "Playwright Chromium не найден. Перезапустите приложение для автоматической установки браузера."
        ) from exc
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=1):
                return
        except Exception:
            time.sleep(0.25)
    raise MaxBrowserError(
        f"Chromium не запустился с remote debugging на {cdp_url}. "
        "Проверьте MAX_CDP_URL и доступность профиля MAX_BROWSER_PROFILE_DIR."
    )


def _read_editor_text(editor: Any) -> str:
    tag_name = editor.evaluate("(node) => node.tagName.toLowerCase()")
    if tag_name in {"input", "textarea", "select"}:
        return editor.input_value()
    return editor.evaluate(
        "(node) => (node.innerText || node.textContent || '').replace(/\\r\\n/g, '\\n')"
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
        if actual == message:
            log.info("MAX: текст вставлен и проверен")
            return actual
        time.sleep(0.1)
    log.warning(
        "MAX: текст вставлен, но проверка не совпала (ожидалось_символов=%d, "
        "получено_символов=%d)",
        len(message),
        len(actual),
    )
    raise MaxBrowserError(
        "MAX открыл чат, но текст в поле сообщения не совпал с подготовленным."
    )


def prepare_message(client_name: str, identity: str, message: str | None) -> PreparationResult:
    """Open a matching MAX chat and put a verified draft in its editor.

    This deliberately never invokes the send control. The browser must already
    be running with remote debugging enabled and an authenticated MAX tab.
    """
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise MaxBrowserError(
            "Для управления браузером установите зависимости из backend\\requirements.txt"
        ) from exc

    cdp_url = os.getenv("MAX_CDP_URL", "http://127.0.0.1:9222").strip()
    editor_selectors = [
        "textarea",
        "[contenteditable='true']",
        "[role='textbox']",
        "[data-testid*='message']",
        "[class*='composer'] [contenteditable='true']",
        "[class*='input'] [contenteditable='true']",
    ]

    try:
        with sync_playwright() as playwright:
            log.info(
                "MAX session.start cdp_url=%s client=%s",
                cdp_url,
                client_name,
            )
            _ensure_cdp_endpoint(playwright, cdp_url)
            try:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
            except Exception as exc:
                raise MaxBrowserError(
                    f"Не удалось подключиться к уже запущенному Chromium через {cdp_url}. "
                    "Запустите Chromium с remote debugging и задайте MAX_CDP_URL."
                ) from exc
            pages = [
                candidate
                for context in browser.contexts
                for candidate in context.pages
                if "max" in candidate.url.casefold()
            ]
            page = next(
                (
                    candidate
                    for candidate in pages
                    if _page_has_controls(candidate)
                ),
                None,
            )
            if page is None and pages:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and page is None:
                    for candidate in pages:
                        try:
                            if _page_has_controls(candidate):
                                page = candidate
                                break
                        except Exception:
                            log.exception(
                                "MAX page readiness check failed url=%s",
                                candidate.url,
                            )
                    if page is None:
                        log.info(
                            "MAX page not ready pages=%s",
                            [candidate.url for candidate in pages],
                        )
                        pages[0].wait_for_timeout(500)
            page = page or (pages[0] if pages else None)
            if page is None:
                raise MaxBrowserError("В подключённом браузере нет открытой вкладки MAX.")
            log.info("MAX: выбрана вкладка MAX %s", page.url)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except PlaywrightTimeoutError:
                log.warning("MAX DOMContentLoaded timeout url=%s", page.url)
            page.wait_for_timeout(1500)
            page.on(
                "console",
                lambda message: log.info(
                    "MAX browser.console type=%s text=%s",
                    message.type,
                    message.text[:1000],
                ),
            )
            page.on(
                "pageerror",
                lambda error: log.error("MAX browser.pageerror %s", error),
            )

            _return_to_main_screen(page)
            search = _open_phone_search(page)
            phone_digits = _max_phone_digits(identity)
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
                    raise MaxBrowserError(
                        "Контакт не найден в MAX по указанному номеру телефона."
                    )
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
    except MaxBrowserError:
        log.exception("MAX preparation failed client=%s", client_name)
        raise
    except PlaywrightTimeoutError as exc:
        log.exception("MAX Playwright timeout client=%s", client_name)
        raise MaxBrowserError(
            "MAX не успел отобразить нужный элемент. Проверьте загрузку вкладки и повторите вручную."
        ) from exc
    except Exception as exc:
        log.exception("MAX unexpected error client=%s", client_name)
        raise MaxBrowserError(
            "Ошибка автоматизации MAX. Подробности записаны в backend\\logs\\session.log."
        ) from exc


def open_chat(client_name: str, identity: str) -> PreparationResult:
    return prepare_message(client_name, identity, None)
