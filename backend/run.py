"""Точка входа приложения: uvicorn с настройками из окружения."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    reload_enabled = os.getenv("APP_RELOAD", "0") == "1"
    uvicorn.run("app.main:app", host=host, port=port, reload=reload_enabled)


if __name__ == "__main__":
    main()
