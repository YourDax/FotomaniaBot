"""Переиспользуемое подключение к MAX: один поток, одно соединение, сброс при сбоях."""

import threading
from typing import Any

import pytest

from app.max_browser import MaxBrowserError, connection
from app.max_browser.connection import MaxSession


class FakeLocator:
    def count(self) -> int:
        return 1


class FakePage:
    def __init__(self, url: str = "https://web.max.ru/") -> None:
        self.url = url
        self.load_waits = 0
        self.settles = 0
        self.listeners: list[str] = []

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator()

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.load_waits += 1

    def wait_for_timeout(self, ms: int) -> None:
        self.settles += 1

    def on(self, event: str, handler: Any) -> None:
        self.listeners.append(event)


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages


class FakeBrowser:
    def __init__(self, pages: list[FakePage]) -> None:
        self.contexts = [FakeContext(pages)]
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected


class FakeChromium:
    def __init__(self, owner: "FakePlaywright") -> None:
        self.owner = owner

    def connect_over_cdp(self, url: str) -> FakeBrowser:
        self.owner.connects += 1
        browser = FakeBrowser(self.owner.pages)
        self.owner.browsers.append(browser)
        return browser


class FakePlaywright:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages
        self.connects = 0
        self.stopped = False
        self.browsers: list[FakeBrowser] = []
        self.chromium = FakeChromium(self)

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def env(monkeypatch):
    page = FakePage()
    started: list[FakePlaywright] = []

    def start() -> FakePlaywright:
        playwright = FakePlaywright([page])
        started.append(playwright)
        return playwright

    monkeypatch.setattr(connection, "_start_playwright", start)
    monkeypatch.setattr(connection, "_ensure_cdp_endpoint", lambda playwright, url: None)
    monkeypatch.setattr(connection, "_cdp_alive", lambda url: True)
    session = MaxSession()
    yield session, page, started
    session.close()


def _run(session: MaxSession, job):
    return session.run(job, label="test", timeout_message="таймаут", unexpected_message="сбой")


def test_connection_and_warm_up_are_reused_between_runs(env):
    session, page, started = env
    assert _run(session, lambda p: p.url) == "https://web.max.ru/"
    assert _run(session, lambda p: p.url) == "https://web.max.ru/"
    assert len(started) == 1
    assert started[0].connects == 1
    assert page.load_waits == 1  # дожидаемся загрузки только при первом обращении к вкладке
    assert page.settles == 1
    assert page.listeners == ["console", "pageerror"]


def test_all_jobs_run_on_one_dedicated_thread(env):
    session, _, _ = env
    names = {_run(session, lambda p: threading.current_thread().name) for _ in range(3)}
    assert len(names) == 1
    assert next(iter(names)).startswith("max-browser")
    assert threading.current_thread().name not in names


def test_lost_connection_is_re_established(env):
    session, _, started = env
    _run(session, lambda p: None)
    started[0].browsers[0].connected = False
    _run(session, lambda p: None)
    assert started[0].stopped  # прежний экземпляр остановлен
    assert len(started) == 2
    assert started[1].connects == 1


def test_unexpected_error_resets_connection_and_is_reported(env):
    session, _, started = env

    def boom(page):
        raise RuntimeError("target closed")

    with pytest.raises(MaxBrowserError, match="сбой"):
        _run(session, boom)
    assert started[0].stopped
    _run(session, lambda p: None)  # следующий вызов подключается заново
    assert len(started) == 2


def test_expected_error_keeps_connection(env):
    session, _, started = env

    def not_found(page):
        raise MaxBrowserError("Контакт не найден")

    with pytest.raises(MaxBrowserError, match="Контакт не найден"):
        _run(session, not_found)
    _run(session, lambda p: None)
    assert len(started) == 1
    assert not started[0].stopped


def test_missing_max_tab_is_reported(monkeypatch):
    playwright = FakePlaywright([FakePage("https://example.org/")])
    monkeypatch.setattr(connection, "_start_playwright", lambda: playwright)
    monkeypatch.setattr(connection, "_ensure_cdp_endpoint", lambda playwright, url: None)
    session = MaxSession()
    try:
        with pytest.raises(MaxBrowserError, match="нет открытой вкладки MAX"):
            _run(session, lambda p: None)
    finally:
        session.close()


def _fake_tabs(monkeypatch, payload):
    import io
    import json
    import urllib.request

    def fake_urlopen(url, timeout):
        if payload is None:
            raise OSError("connection refused")
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_status_reports_ready_no_tab_and_offline(monkeypatch):
    _fake_tabs(monkeypatch, [{"type": "page", "url": "https://web.max.ru/"}])
    assert connection.status() == "ready"
    _fake_tabs(monkeypatch, [{"type": "page", "url": "https://example.org/"}])
    assert connection.status() == "no_tab"
    _fake_tabs(monkeypatch, [{"type": "service_worker", "url": "https://web.max.ru/sw.js"}])
    assert connection.status() == "no_tab"
    _fake_tabs(monkeypatch, None)
    assert connection.status() == "offline"


def test_closed_browser_is_detected_before_the_next_run(env, monkeypatch):
    session, _, started = env
    _run(session, lambda p: None)
    # браузер закрыт, а Playwright ещё не заметил
    monkeypatch.setattr(connection, "_cdp_alive", lambda url: False)
    _run(session, lambda p: None)
    assert started[0].stopped and len(started) == 2


class TargetClosedError(Exception):
    """Имя совпадает с исключением Playwright о закрытом браузере."""


def test_stale_connection_error_is_retried_once_with_a_new_connection(env):
    session, _, started = env
    _run(session, lambda p: None)
    calls = []

    def job(page):
        calls.append(1)
        if len(calls) == 1:
            raise TargetClosedError("Target page, context or browser has been closed")
        return "ok"

    assert _run(session, job) == "ok"
    assert len(calls) == 2 and len(started) == 2


def test_closed_error_on_a_fresh_connection_is_not_retried(env):
    session, _, started = env
    calls = []

    def job(page):
        calls.append(1)
        raise TargetClosedError("closed")

    with pytest.raises(MaxBrowserError, match="сбой"):
        _run(session, job)
    assert len(calls) == 1


def test_close_disconnects_and_allows_reuse(env):
    session, _, started = env
    _run(session, lambda p: None)
    session.close()
    assert started[0].stopped
    session.close()  # повторное закрытие безопасно
    _run(session, lambda p: None)  # после закрытия сессия снова работоспособна
    assert len(started) == 2
