"""Подключение к уже запущенному Chromium с вкладкой MAX по CDP.

Playwright (sync API) привязан к потоку, поэтому им владеет один выделенный поток:
все операции с MAX выполняются в нём по очереди, а соединение с браузером
переиспользуется между вызовами, пока оно живо. При обрыве или неожиданной ошибке
соединение сбрасывается и следующий вызов подключается заново.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

from ..db import BASE_DIR
from .page import _page_has_controls
from .results import MaxBrowserError

log = logging.getLogger("fotomaniabot.max_browser")

T = TypeVar("T")

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
PROJECT_ROOT = BASE_DIR.parent
PAGE_READY_TIMEOUT = 20.0
PAGE_LOAD_TIMEOUT_MS = 15000
PAGE_SETTLE_MS = 1500


def cdp_url() -> str:
    return os.getenv("MAX_CDP_URL", DEFAULT_CDP_URL).strip()


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
    profile = (
        Path(configured_profile) if configured_profile else (PROJECT_ROOT / ".max-browser-profile")
    )
    if not profile.is_absolute():
        profile = PROJECT_ROOT / profile
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


def _start_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise MaxBrowserError(
            "Для управления браузером установите зависимости из backend\\requirements.txt"
        ) from exc
    return sync_playwright().start()


def _timeout_errors() -> tuple[type[BaseException], ...]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except ImportError:
        return ()
    return (PlaywrightTimeoutError,)


class MaxSession:
    """Одно переиспользуемое подключение к MAX; операции выполняются по очереди."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._playwright: Any = None
        self._browser: Any = None
        self._browser_url: str | None = None
        self._warmed_pages: list[Any] = []

    # --- вызывается из любых потоков -------------------------------------------------

    def run(
        self,
        job: Callable[[Any], T],
        *,
        label: str,
        timeout_message: str,
        unexpected_message: str,
    ) -> T:
        """Выполнить `job(page)` в потоке сессии; ошибки приводятся к MaxBrowserError."""
        with self._guard:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="max-browser")
            executor = self._executor
        return executor.submit(
            self._execute, job, label, timeout_message, unexpected_message
        ).result()

    def close(self) -> None:
        """Отключиться от браузера и остановить поток (при остановке приложения)."""
        with self._guard:
            executor, self._executor = self._executor, None
        if executor is None:
            return
        try:
            executor.submit(self._reset).result(timeout=10)
        except Exception:
            log.exception("MAX: не удалось корректно закрыть соединение с браузером")
        executor.shutdown(wait=False)

    # --- выполняется только в потоке сессии -----------------------------------------

    def _execute(
        self,
        job: Callable[[Any], T],
        label: str,
        timeout_message: str,
        unexpected_message: str,
    ) -> T:
        try:
            return job(self._acquire_page())
        except MaxBrowserError:
            log.exception("MAX %s failed", label)
            raise
        except _timeout_errors() as exc:
            log.exception("MAX %s Playwright timeout", label)
            raise MaxBrowserError(timeout_message) from exc
        except Exception as exc:
            log.exception("MAX %s unexpected error", label)
            self._reset()  # состояние браузера неизвестно: следующий вызов подключится заново
            raise MaxBrowserError(unexpected_message) from exc

    def _reset(self) -> None:
        playwright, self._playwright = self._playwright, None
        self._browser = None
        self._browser_url = None
        self._warmed_pages = []
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                log.exception("MAX: ошибка при остановке Playwright")

    def _acquire_page(self) -> Any:
        url = cdp_url()
        if self._browser is not None and (
            url != self._browser_url or not self._browser.is_connected()
        ):
            log.info("MAX: соединение с браузером потеряно или изменено, подключаюсь заново")
            self._reset()
        if self._playwright is None:
            self._playwright = _start_playwright()
        if self._browser is None:
            _ensure_cdp_endpoint(self._playwright, url)
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(url)
            except Exception as exc:
                raise MaxBrowserError(
                    f"Не удалось подключиться к уже запущенному Chromium через {url}. "
                    "Запустите Chromium с remote debugging и задайте MAX_CDP_URL."
                ) from exc
            self._browser_url = url
            self._warmed_pages = []
        else:
            log.info("MAX: использую существующее соединение с браузером")
        page = self._select_page(self._browser)
        self._warm_up(page)
        return page

    @staticmethod
    def _select_page(browser: Any) -> Any:
        pages = [
            candidate
            for context in browser.contexts
            for candidate in context.pages
            if "max" in candidate.url.casefold()
        ]
        if not pages:
            raise MaxBrowserError("В подключённом браузере нет открытой вкладки MAX.")
        page = next((candidate for candidate in pages if _page_has_controls(candidate)), None)
        deadline = time.monotonic() + PAGE_READY_TIMEOUT
        while page is None and time.monotonic() < deadline:
            pages[0].wait_for_timeout(500)
            page = next((candidate for candidate in pages if _page_has_controls(candidate)), None)
            if page is None:
                log.info("MAX page not ready pages=%s", [candidate.url for candidate in pages])
        page = page or pages[0]
        log.info("MAX: выбрана вкладка MAX %s", page.url)
        return page

    def _warm_up(self, page: Any) -> None:
        """Один раз на вкладку: дождаться загрузки и подключить журнал консоли."""
        if any(known is page for known in self._warmed_pages):
            return
        try:
            page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
        except _timeout_errors():
            log.warning("MAX DOMContentLoaded timeout url=%s", page.url)
        page.wait_for_timeout(PAGE_SETTLE_MS)
        page.on(
            "console",
            lambda message: log.info(
                "MAX browser.console type=%s text=%s", message.type, message.text[:1000]
            ),
        )
        page.on("pageerror", lambda error: log.error("MAX browser.pageerror %s", error))
        self._warmed_pages.append(page)


_session = MaxSession()


def get_session() -> MaxSession:
    return _session


def shutdown() -> None:
    _session.close()
