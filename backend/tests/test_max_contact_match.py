"""Tests for reusing the chat that is already open in MAX when its header matches the contact."""

from typing import Any

import pytest

from app.max_browser import (
    _PROFILE_BUTTON_PREFIX,
    _open_chat_is_for_contact,
    normalize_contact_name,
)

EXPECTED = "РК тест 5в - 2026 Амалия Ивановна"


class FakeLocator:
    def __init__(self, label: str | None, count: int) -> None:
        self._label = label
        self._count = count

    def count(self) -> int:
        return self._count

    def nth(self, index: int) -> "FakeLocator":
        return self

    @property
    def first(self) -> "FakeLocator":
        return self

    def is_visible(self, timeout: float | None = None) -> bool:
        return False

    def inner_text(self, timeout: float | None = None) -> str:
        return ""

    def get_attribute(self, name: str, timeout: float | None = None) -> str | None:
        return self._label


class FakeHeaderPage:
    def __init__(self, label: str | None, count: int = 1) -> None:
        self._label = label
        self._count = count

    def locator(self, selector: str) -> FakeLocator:
        if selector.startswith("button[aria-label^="):
            return FakeLocator(self._label, self._count)
        return FakeLocator(None, 0)


def _page(label: str | None, count: int = 1) -> Any:
    return FakeHeaderPage(label, count)


def test_normalize_ignores_case_yo_dashes_and_spaces() -> None:
    assert normalize_contact_name("  РК   Тест 5В –  2026 Амалия  Ивановна ") == normalize_contact_name(
        "рк тест 5в - 2026 амалия ивановна"
    )
    assert normalize_contact_name("Ёлка") == normalize_contact_name("елка")


def test_exact_header_name_matches() -> None:
    page = _page(f"{_PROFILE_BUTTON_PREFIX}{EXPECTED}")
    assert _open_chat_is_for_contact(page, EXPECTED) is True


def test_partial_name_does_not_match() -> None:
    page = _page(f"{_PROFILE_BUTTON_PREFIX}РК тест 5в - 2026 Амалия")
    assert _open_chat_is_for_contact(page, EXPECTED) is False


def test_other_contact_does_not_match() -> None:
    page = _page(f"{_PROFILE_BUTTON_PREFIX}РК тест 6а - 2026 Иван Петрович")
    assert _open_chat_is_for_contact(page, EXPECTED) is False


def test_truncated_header_is_unknown() -> None:
    page = _page(f"{_PROFILE_BUTTON_PREFIX}РК тест 5в - 2026 Амалия...")
    assert _open_chat_is_for_contact(page, EXPECTED) is False


def test_no_header_means_not_matched() -> None:
    assert _open_chat_is_for_contact(_page(None, count=0), EXPECTED) is False


def test_missing_expected_name_means_not_matched() -> None:
    page = _page(f"{_PROFILE_BUTTON_PREFIX}{EXPECTED}")
    assert _open_chat_is_for_contact(page, None) is False
    assert _open_chat_is_for_contact(page, "   ") is False


@pytest.mark.parametrize("broken", [None, ""])
def test_empty_profile_label_is_unknown(broken: str | None) -> None:
    assert _open_chat_is_for_contact(_page(broken), EXPECTED) is False
