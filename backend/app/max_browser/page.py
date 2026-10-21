"""Общие приёмы работы со страницей MAX: поиск видимых элементов, кнопка «назад», журнал DOM."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from ..db import BASE_DIR

log = logging.getLogger("fotomaniabot.max_browser")

CHAT_BACK_ATTEMPTS = 8
FIRST_NAME_INPUT_SELECTOR = "input[name='firstName']"
# Info/profile panel overlays the chat as an absolutely positioned layer with its own back arrow.
OVERLAY_BACK_SELECTOR = "[class~='absolute'] button[aria-label*='назад' i]"
CHAT_BACK_SELECTOR = "button[aria-label*='назад' i]"


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
                if candidate.is_visible(timeout=300) and candidate.is_editable(timeout=300):
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
                button_data.append(
                    item.evaluate(
                        "(node) => ({text: node.innerText, aria: node.getAttribute('aria-label'), "
                        "title: node.getAttribute('title'), html: node.outerHTML.slice(0, 500)})"
                    )
                )
        inputs = page.locator("input")
        input_data = []
        for index in range(min(inputs.count(), 40)):
            item = inputs.nth(index)
            if item.is_visible():
                input_data.append(
                    item.evaluate(
                        "(node) => ({type: node.type, placeholder: node.placeholder, "
                        "autocomplete: node.autocomplete, inputmode: node.inputMode, className: node.className})"
                    )
                )
        log.info(
            "MAX DOM stage=%s url=%s title=%s buttons=%s inputs=%s",
            stage,
            page.url,
            page.title(),
            button_data,
            input_data,
        )
        if os.getenv("MAX_SAVE_DOM_LOG", "0") == "1":
            log_dir = BASE_DIR / "logs"
            log_dir.mkdir(exist_ok=True)
            snapshot = log_dir / f"max-{int(time.time())}-{stage}.html"
            snapshot.write_text(page.content(), encoding="utf-8")
            log.info("MAX DOM snapshot saved path=%s", snapshot)
    except Exception:
        log.exception("MAX DOM logging failed stage=%s", stage)


def _find_back_button(page: Any) -> Any | None:
    """Prefer the overlay's back arrow: pressing the chat header's arrow would leave the chat."""
    return _first_visible_locator(
        page,
        [page.locator(OVERLAY_BACK_SELECTOR), page.locator(CHAT_BACK_SELECTOR)],
    )
