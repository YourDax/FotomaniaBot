"""Задания рассылки и действия в MAX."""

from __future__ import annotations

import logging
import threading
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from ..db import session_scope
from ..max_browser import MaxBrowserError, open_chat, prepare_message, rename_contact
from ..message_sets import MAX_MESSAGES_PER_ROLE, save_task_messages, task_messages
from ..models import (
    Client,
    DeliveryTask,
    School,
    SchoolClass,
    now,
)
from ..schemas import (
    ManualResultIn,
    TaskMessageIn,
    TaskStatusIn,
)
from ..services import (
    contact_first_name,
)
from .campaigns import MESSAGE_EDITABLE_STATUSES

log = logging.getLogger("fotomaniabot")
router = APIRouter()


# Одновременно в MAX работает одна операция: параллельные сценарии на одной вкладке
# портят друг другу поле ввода (особенно при нескольких кнопках «Подготовить в MAX»).
max_lock = threading.Lock()
MAX_BUSY_MESSAGE = "В MAX ещё выполняется другая операция. Дождитесь её завершения и повторите."

NOT_FOUND_STATUS = "CONTACT_NOT_FOUND"
NOT_FOUND_CLEARING_STATUSES = frozenset({"SENT"})


def _guard_not_found_mark(task: DeliveryTask, new_status: str) -> None:
    """Пометка «Не найден в MAX» снимается только положительным ручным статусом."""
    if task.status != NOT_FOUND_STATUS or new_status == NOT_FOUND_STATUS:
        return
    if new_status not in NOT_FOUND_CLEARING_STATUSES:
        raise HTTPException(
            409,
            "Пометку «Не найден в MAX» снимает только ручной статус «Готово» (SENT)",
        )


def _task_and_contact(session: Any, task_id: int) -> tuple[DeliveryTask, Client]:
    task = session.get(DeliveryTask, task_id)
    if task is None:
        raise HTTPException(404, "Задача не найдена")
    contact = session.get(Client, task.client_id)
    if contact is None:
        raise HTTPException(404, "Клиент задачи не найден")
    return task, contact


def _contact_identity(contact: Client) -> str:
    return contact.max_user_id or contact.chat_link or contact.username or ""


@router.post("/api/tasks/{task_id}/prepare-max")
def prepare_max_task(
    task_id: int,
    message_no: Annotated[int, Query(ge=1, le=MAX_MESSAGES_PER_ROLE)] = 1,
) -> dict[str, Any]:
    with session_scope() as session:
        task, contact = _task_and_contact(session, task_id)
        messages = task_messages(task)
        if not messages:
            raise HTTPException(422, "Для этого задания нет текста сообщения")
        if message_no > len(messages):
            raise HTTPException(
                422, f"У задания {len(messages)} сообщ., сообщения №{message_no} нет"
            )
        if not contact.phone:
            raise HTTPException(502, "У контакта не указан номер телефона для поиска в MAX")
        client_name = contact.name
        identity = contact.phone
        message = messages[message_no - 1]["text"]
        if not message.strip():
            raise HTTPException(422, f"Текст сообщения №{message_no} пустой")
        school = session.get(School, contact.school_id) if contact.school_id else None
        school_class = session.get(SchoolClass, contact.class_id) if contact.class_id else None
        try:
            expected_name: str | None = contact_first_name(
                task.recipient_role,
                school.name if school else "",
                school_class.name if school_class else "",
                contact.name,
                now().astimezone().year,
            )
        except ValueError:
            expected_name = None
    if not max_lock.acquire(blocking=False):
        raise HTTPException(409, MAX_BUSY_MESSAGE)
    try:
        result = prepare_message(client_name, identity, message, expected_name=expected_name)
    except MaxBrowserError as exc:
        with session_scope() as session:
            failed = session.get(DeliveryTask, task_id)
            if failed is not None:
                if "не найден" in str(exc).casefold():
                    failed.status = "CONTACT_NOT_FOUND"
                    failed.browser_error = None
                else:
                    failed.browser_error = str(exc)
                session.commit()
        raise HTTPException(502, str(exc)) from exc
    finally:
        max_lock.release()
    with session_scope() as session:
        task = session.get(DeliveryTask, task_id)
        if task is not None:
            items = task_messages(task)
            # Текст могли изменить, пока шла подготовка: отмечаем только совпавший.
            if message_no <= len(items) and items[message_no - 1]["text"] == message:
                items[message_no - 1]["prepared_at"] = now().isoformat()
                save_task_messages(task, items)
            task.browser_error = None
            session.commit()
    return {
        "status": result.status,
        "page_url": result.page_url,
        "client": result.client_name,
        "message_no": message_no,
    }


@router.post("/api/tasks/{task_id}/open-max")
def open_max_task(task_id: int) -> dict[str, Any]:
    with session_scope() as session:
        task, contact = _task_and_contact(session, task_id)
        client_name = contact.name
        identity = contact.phone or _contact_identity(contact)
        school = session.get(School, contact.school_id) if contact.school_id else None
        school_class = session.get(SchoolClass, contact.class_id) if contact.class_id else None
        try:
            expected_name: str | None = contact_first_name(
                task.recipient_role,
                school.name if school else "",
                school_class.name if school_class else "",
                contact.name,
                now().astimezone().year,
            )
        except ValueError:
            expected_name = None
    if not max_lock.acquire(blocking=False):
        raise HTTPException(409, MAX_BUSY_MESSAGE)
    try:
        result = open_chat(client_name, identity, expected_name=expected_name)
    except MaxBrowserError as exc:
        with session_scope() as session:
            failed = session.get(DeliveryTask, task_id)
            if failed is not None:
                if "не найден" in str(exc).casefold():
                    failed.status = NOT_FOUND_STATUS
                    failed.browser_error = None
                else:
                    failed.browser_error = str(exc)
                session.commit()
        raise HTTPException(502, str(exc)) from exc
    finally:
        max_lock.release()
    with session_scope() as session:
        task = session.get(DeliveryTask, task_id)
        if task is not None:
            task.opened_at = now()
            task.browser_error = None
            session.commit()
    return {"status": result.status, "page_url": result.page_url, "client": result.client_name}


@router.post("/api/tasks/{task_id}/rename-max")
def rename_max_task(task_id: int) -> dict[str, Any]:
    with session_scope() as session:
        task, contact = _task_and_contact(session, task_id)
        if not contact.phone:
            raise HTTPException(502, "У контакта не указан номер телефона для поиска в MAX")
        school = session.get(School, contact.school_id) if contact.school_id else None
        school_class = session.get(SchoolClass, contact.class_id) if contact.class_id else None
        try:
            first_name = contact_first_name(
                task.recipient_role,
                school.name if school else "",
                school_class.name if school_class else "",
                contact.name,
                now().astimezone().year,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        client_name = contact.name
        identity = contact.phone
    if not max_lock.acquire(blocking=False):
        raise HTTPException(409, MAX_BUSY_MESSAGE)
    try:
        result = rename_contact(client_name, identity, first_name)
    except MaxBrowserError as exc:
        with session_scope() as session:
            failed = session.get(DeliveryTask, task_id)
            if failed is not None:
                failed.browser_error = str(exc)
                session.commit()
        raise HTTPException(502, str(exc)) from exc
    finally:
        max_lock.release()
    return {
        "status": result.status,
        "client": result.client_name,
        "first_name": result.first_name,
    }


@router.patch("/api/tasks/{task_id}/message")
def update_task_message(
    task_id: int, data: TaskMessageIn
) -> dict[str, Any]:
    text = data.message.strip()
    if not text:
        raise HTTPException(422, "Текст сообщения не может быть пустым")
    with session_scope() as session:
        task, _contact = _task_and_contact(session, task_id)
        if task.status not in MESSAGE_EDITABLE_STATUSES:
            raise HTTPException(409, "Текст можно менять только у необработанных заданий")
        items = task_messages(task) or [{"text": "", "prepared_at": None}]
        if data.index > len(items):
            raise HTTPException(422, f"У задания {len(items)} сообщ., сообщения №{data.index} нет")
        if text != items[data.index - 1]["text"]:
            items[data.index - 1] = {"text": text, "prepared_at": None}
            save_task_messages(task, items)
        session.commit()
        return {
            "id": task.id,
            "message": task.rendered_message,
            "index": data.index,
            "status": task.status,
        }


@router.post("/api/tasks/{task_id}/opened")
def mark_task_opened(task_id: int) -> dict[str, Any]:
    with session_scope() as session:
        task, _contact = _task_and_contact(session, task_id)
        task.opened_at = now()
        session.commit()
        return {"id": task.id, "opened_at": task.opened_at}


@router.patch("/api/tasks/{task_id}/status")
def update_task_status(
    task_id: int, data: TaskStatusIn
) -> dict[str, Any]:
    with session_scope() as session:
        task, _contact = _task_and_contact(session, task_id)
        _guard_not_found_mark(task, data.status)
        task.status = data.status
        if data.status in {"SENT", "FAILED", "CANCELLED"}:
            task.finished_at = now()
        session.commit()
        return {"id": task.id, "status": task.status}



@router.post("/api/tasks/{task_id}/confirm")
def confirm_manual_task(
    task_id: int, data: ManualResultIn
) -> dict[str, Any]:
    with session_scope() as session:
        task, _contact = _task_and_contact(session, task_id)
        mapping = {"sent": "SENT", "failed": "FAILED", "unknown": "UNKNOWN"}
        _guard_not_found_mark(task, mapping[data.result])
        task.operator_result = data.result
        task.operator_confirmed_at = now()
        task.status = mapping[data.result]
        task.requires_review = False
        if data.note:
            task.error = data.note
        if task.status in {"SENT", "FAILED"}:
            task.finished_at = now()
        session.commit()
        return {"id": task.id, "status": task.status, "operator_result": task.operator_result}
