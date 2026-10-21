from __future__ import annotations

import logging
import os
import re
import subprocess
import time
import unicodedata
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


def _click_back_button(back: Any) -> None:
    """Click «Перейти назад». Playwright's click can be blocked by a transient overlay
    (the arrow's <use> icon from a neighbouring layout subtree), so fall back to a DOM click.
    """
    try:
        back.click(timeout=3000)
    except Exception:
        log.warning("MAX: кнопка «назад» перекрыта, нажимаю через DOM")
        back.evaluate("(node) => node.click()")


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
    _click_back_button(back)
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
        _mismatch_details(
            _comparable_message_text(message), _comparable_message_text(actual)
        ),
    )
    raise MaxBrowserError(
        "MAX открыл чат, но текст в поле сообщения не совпал с подготовленным."
    )


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
                title = label[len(_PROFILE_BUTTON_PREFIX):].strip()
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

            if _open_chat_is_for_contact(page, expected_name):
                prepared = _prepare_draft_in_open_chat(page, client_name, message)
                if prepared is not None:
                    log.info("MAX: черновик подготовлен в уже открытом чате, поиск по номеру не нужен")
                    return prepared
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


def open_chat(
    client_name: str, identity: str, expected_name: str | None = None
) -> PreparationResult:
    return prepare_message(client_name, identity, None, expected_name=expected_name)


CHAT_EDITOR_SELECTORS: list[str] = [
    "div[data-text-entry='true'][contenteditable]",
    "textarea",
    "[contenteditable='true']",
    "[role='textbox']",
    "[data-testid*='message']",
    "[class*='composer'] [contenteditable='true']",
    "[class*='input'] [contenteditable='true']",
]


@dataclass
class RenameResult:
    status: str
    page_url: str
    client_name: str
    first_name: str


def _connect_max_page(playwright: Any, cdp_url: str) -> Any:
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
    if not pages:
        raise MaxBrowserError("В подключённом браузере нет открытой вкладки MAX.")
    page = None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and page is None:
        page = next((candidate for candidate in pages if _page_has_controls(candidate)), None)
        if page is None:
            time.sleep(0.5)
    page = page or pages[0]
    log.info("MAX: выбрана вкладка MAX %s", page.url)
    return page


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


def _save_contact_name(
    page: Any, first_name_input: Any, first_name: str, add_mode: bool
) -> bool:
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


CHAT_BACK_ATTEMPTS = 8
FIRST_NAME_INPUT_SELECTOR = "input[name='firstName']"
# Info/profile panel overlays the chat as an absolutely positioned layer with its own back arrow.
OVERLAY_BACK_SELECTOR = "[class~='absolute'] button[aria-label*='назад' i]"
CHAT_BACK_SELECTOR = "button[aria-label*='назад' i]"


def _open_chat_editor(page: Any) -> Any | None:
    """Return the visible message input only when the chat is really in front (no overlay, no contact form)."""
    if _first_visible_locator(page, [page.locator(FIRST_NAME_INPUT_SELECTOR)]) is not None:
        return None
    if _first_visible_locator(page, [page.locator(OVERLAY_BACK_SELECTOR)]) is not None:
        return None
    return _first_visible(page, CHAT_EDITOR_SELECTORS)


def _find_back_button(page: Any) -> Any | None:
    """Prefer the overlay's back arrow: pressing the chat header's arrow would leave the chat."""
    return _first_visible_locator(
        page,
        [page.locator(OVERLAY_BACK_SELECTOR), page.locator(CHAT_BACK_SELECTOR)],
    )


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


def rename_contact(client_name: str, identity: str, first_name: str) -> RenameResult:
    """Rename a MAX contact found by phone. Never sends or edits chat messages."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise MaxBrowserError(
            "Для управления браузером установите зависимости из backend\\requirements.txt"
        ) from exc

    cdp_url = os.getenv("MAX_CDP_URL", "http://127.0.0.1:9222").strip()
    try:
        with sync_playwright() as playwright:
            log.info("MAX rename.start cdp_url=%s client=%s", cdp_url, client_name)
            page = _connect_max_page(playwright, cdp_url)
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
    except MaxBrowserError:
        log.exception("MAX rename failed client=%s", client_name)
        raise
    except PlaywrightTimeoutError as exc:
        log.exception("MAX rename Playwright timeout client=%s", client_name)
        raise MaxBrowserError(
            "MAX не успел отобразить форму контакта. Повторите переименование вручную."
        ) from exc
    except Exception as exc:
        log.exception("MAX rename unexpected error client=%s", client_name)
        raise MaxBrowserError(
            "Ошибка автоматизации MAX при переименовании. "
            "Подробности записаны в журнале backend."
        ) from exc

