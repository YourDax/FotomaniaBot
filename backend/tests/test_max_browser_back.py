"""Regression tests: after a contact rename the bot walks back to the chat with «назад».

Screens: "form" (contact editor) -> "overlay" (info panel with its own back arrow) -> "chat".
"""

from typing import Any

import pytest

from app.max_browser import (
    CHAT_BACK_ATTEMPTS,
    CHAT_BACK_SELECTOR,
    FIRST_NAME_INPUT_SELECTOR,
    OVERLAY_BACK_SELECTOR,
    MaxBrowserError,
    _return_to_chat_after_rename,
)

BACK_NAME = "Перейти назад"
EDITOR_SELECTOR = "textarea"


class FakeLocator:
    def __init__(self, page: "FakePage", key: Any) -> None:
        self._page = page
        self._key = key

    def _matches(self) -> bool:
        screen = self._page.screen
        if self._key == EDITOR_SELECTOR:
            return screen == "chat"
        if self._key == FIRST_NAME_INPUT_SELECTOR:
            return screen == "form"
        if self._key == OVERLAY_BACK_SELECTOR:
            return screen == "overlay"
        if self._key in (CHAT_BACK_SELECTOR, ("role", "button", BACK_NAME)):
            return screen in ("form", "overlay")
        return False

    def count(self) -> int:
        return 1 if self._matches() else 0

    def nth(self, index: int) -> "FakeLocator":
        return self

    def is_visible(self, timeout: float | None = None) -> bool:
        return self._matches()

    def is_editable(self, timeout: float | None = None) -> bool:
        return self._matches()

    def click(self, timeout: float | None = None) -> None:
        page = self._page
        if self._key == EDITOR_SELECTOR:
            page.editor_clicks += 1
            return
        if self._key == OVERLAY_BACK_SELECTOR and page.overlay_back_blocked:
            raise RuntimeError("intercepts pointer events")
        page.press_back(self._key)

    def evaluate(self, expression: str) -> None:
        self._page.dom_clicks += 1
        self._page.press_back(self._key)


class FakePage:
    def __init__(self, screen: str, overlay_back_blocked: bool = False, stuck: bool = False) -> None:
        self.screen = screen
        self.overlay_back_blocked = overlay_back_blocked
        self.stuck = stuck
        self.back_clicks = 0
        self.dom_clicks = 0
        self.editor_clicks = 0
        self.wrong_clicks = 0
        self.url = "https://web.max.ru/"

    def press_back(self, key: Any) -> None:
        self.back_clicks += 1
        if self.stuck:
            return
        if key == CHAT_BACK_SELECTOR and self.screen == "overlay":
            # Header arrow pressed while the overlay is open: must never happen.
            self.wrong_clicks += 1
        if self.screen == "form":
            self.screen = "overlay"
        elif self.screen == "overlay":
            self.screen = "chat"

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def get_by_role(self, role: str, name: str | None = None) -> FakeLocator:
        return FakeLocator(self, ("role", role, name))

    def wait_for_timeout(self, timeout: float) -> None:
        return None

    def title(self) -> str:
        return "MAX"

    def content(self) -> str:
        return ""


def test_walks_form_then_overlay_back_to_chat_without_touching_header_arrow() -> None:
    page = FakePage(screen="form")

    _return_to_chat_after_rename(page)

    assert page.screen == "chat"
    assert page.wrong_clicks == 0
    assert page.editor_clicks == 1


def test_falls_back_to_dom_click_when_overlay_back_is_intercepted() -> None:
    page = FakePage(screen="overlay", overlay_back_blocked=True)

    _return_to_chat_after_rename(page)

    assert page.dom_clicks == 1
    assert page.screen == "chat"
    assert page.editor_clicks == 1


def test_no_back_click_when_chat_already_open() -> None:
    page = FakePage(screen="chat")

    _return_to_chat_after_rename(page)

    assert page.back_clicks == 0
    assert page.editor_clicks == 1


def test_raises_when_chat_never_opens() -> None:
    page = FakePage(screen="form", stuck=True)

    with pytest.raises(MaxBrowserError):
        _return_to_chat_after_rename(page)

    assert page.back_clicks == CHAT_BACK_ATTEMPTS
    assert page.editor_clicks == 0
