"""FastAPI-приложение: сборка, логирование, жизненный цикл и статика.

Маршруты вынесены в пакет `routers`, воркер — в `worker`, модели, схемы,
доступ к БД и прикладные функции — в `models`, `schemas`, `db`, `services`.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from . import max_browser, worker
from .db import BASE_DIR, DATABASE_URL, engine
from .migrations import apply_migrations
from .models import Base
from .routers import campaigns, clients, imports, reports, schools, tasks

log = logging.getLogger("fotomaniabot")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
if not any(isinstance(handler, logging.FileHandler) for handler in log.handlers):
    file_handler = RotatingFileHandler(
        LOG_DIR / "session.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(file_handler)
    # Сообщения uvicorn (запуск, ошибки, доступ) тоже сохраняем в журнал сессии.
    for _name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(_name).addHandler(file_handler)

MAX_SNAPSHOTS = 20
HEALTH_PATH = "/api/health"
WEB_ROOT = Path(__file__).parent / "static"


def _purge_old_snapshots() -> None:
    """Keep the newest MAX DOM snapshots, drop the rest to bound disk usage."""
    snapshots = sorted(LOG_DIR.glob("max-*.html"), key=lambda path: path.stat().st_mtime)
    for stale in snapshots[:-MAX_SNAPSHOTS]:
        try:
            stale.unlink()
        except OSError:
            log.warning("Не удалось удалить старый снимок MAX %s", stale)


def init_db() -> None:
    """Create missing tables and apply migrations. Idempotent and safe to repeat."""
    Base.metadata.create_all(engine)
    apply_migrations(engine)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    _purge_old_snapshots()
    worker.start_worker()
    log.info("База данных: %s", DATABASE_URL)
    log.info("Журнал сессии: %s", LOG_DIR / "session.log")
    log.info("Приложение запущено; подготовка сообщений в MAX доступна через CDP")
    try:
        yield
    finally:
        worker.stop_worker()
        max_browser.shutdown()


app = FastAPI(title="MAX Рассылки", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def request_logging(request: Request, call_next: Any) -> Any:
    if request.url.path == HEALTH_PATH:
        return await call_next(request)
    request_id = uuid.uuid4().hex[:12]
    started = time.monotonic()
    log.info("request.start id=%s method=%s path=%s", request_id, request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        log.exception(
            "request.error id=%s method=%s path=%s", request_id, request.method, request.url.path
        )
        raise
    duration_ms = round((time.monotonic() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    log.info(
        "request.end id=%s status=%s duration_ms=%s",
        request_id,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html", headers=NO_CACHE)


# Без этого браузер эвристически кеширует скрипты и работает со старым кодом
# поверх нового index.html; no-cache заставляет проверять ETag при каждой загрузке.
NO_CACHE = {"Cache-Control": "no-cache"}

UI_ASSETS: dict[str, str] = {"styles.css": "text/css; charset=utf-8"}
JS_MODULE_NAME = re.compile(r"^[a-z_]+\.js$")


@app.get("/static/{asset_name}", include_in_schema=False)
def ui_asset(asset_name: str) -> FileResponse:
    """Отдаёт файлы интерфейса с явным MIME-типом.

    StaticFiles/mimetypes зависят от реестра Windows, где .js может оказаться
    text/plain, а строгая проверка MIME в Chrome тогда отклонит стили и скрипты.
    """
    media_type = UI_ASSETS.get(asset_name)
    path = WEB_ROOT / asset_name
    if media_type is None or not path.is_file():
        raise HTTPException(404, "Файл интерфейса не найден")
    return FileResponse(path, media_type=media_type, headers=NO_CACHE)


@app.get("/static/js/{asset_name}", include_in_schema=False)
def ui_script(asset_name: str) -> FileResponse:
    """ES-модули интерфейса (static/js/*.js) с явным JavaScript MIME-типом."""
    path = WEB_ROOT / "js" / asset_name
    if not JS_MODULE_NAME.match(asset_name) or not path.is_file():
        raise HTTPException(404, "Модуль интерфейса не найден")
    return FileResponse(path, media_type="text/javascript; charset=utf-8", headers=NO_CACHE)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "worker": worker.is_alive(),
        "integration": "browser_cdp",
        "max": max_browser.status(),
        "mode": "manual",
    }


for _router in (schools, clients, campaigns, imports, tasks, reports):
    app.include_router(_router.router)
