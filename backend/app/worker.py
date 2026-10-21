"""Фоновый воркер, переводящий задания запущенных рассылок в очередь проверки."""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .db import session_scope
from .models import Campaign, DeliveryTask, now

log = logging.getLogger("fotomaniabot")

worker_lock = threading.Lock()
worker_thread: threading.Thread | None = None
worker_stop = threading.Event()
worker_wake = threading.Event()
IDLE_POLL_SECONDS = 30.0


def _process_next() -> bool:
    """Handle one pending task of the first running campaign; False if idle."""
    with session_scope() as session:
        campaign = session.scalar(
            select(Campaign).where(Campaign.status == "RUNNING").order_by(Campaign.id)
        )
        if campaign is None:
            return False
        task = session.scalar(
            select(DeliveryTask).where(
                DeliveryTask.campaign_id == campaign.id,
                DeliveryTask.status == "PENDING",
            )
        )
        if task is None:
            if session.scalar(
                select(DeliveryTask).where(
                    DeliveryTask.campaign_id == campaign.id,
                    DeliveryTask.status == "REQUIRES_REVIEW",
                )
            ):
                campaign.status = "WAITING_REVIEW"
            else:
                campaign.status = "COMPLETED"
                campaign.finished_at = now()
            session.commit()
            return True
        task.status = "PROCESSING"
        task.started_at = now()
        task.attempts += 1
        if campaign.mode == "manual":
            task.status = "REQUIRES_REVIEW"
            task.error = "Ожидается подтверждение оператора"
            task.requires_review = True
        task.finished_at = now()
        session.commit()
        return True


def _run_worker() -> None:
    # Просыпаемся по сигналу (запуск рассылки, старт приложения); таймаут — лишь страховка.
    while not worker_stop.is_set():
        worker_wake.wait(timeout=IDLE_POLL_SECONDS)
        worker_wake.clear()
        try:
            while not worker_stop.is_set() and _process_next():
                pass
        except SQLAlchemyError:
            log.exception("delivery-worker iteration failed")
            time.sleep(0.5)


def start_worker() -> None:
    global worker_thread
    with worker_lock:
        if worker_thread is None or not worker_thread.is_alive():
            worker_stop.clear()
            worker_thread = threading.Thread(
                target=_run_worker, daemon=True, name="delivery-worker"
            )
            worker_thread.start()
            worker_wake.set()  # подхватить рассылки, запущенные до перезапуска


def stop_worker() -> None:
    worker_stop.set()
    worker_wake.set()
    thread = worker_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=2)


def is_alive() -> bool:
    return bool(worker_thread and worker_thread.is_alive())
