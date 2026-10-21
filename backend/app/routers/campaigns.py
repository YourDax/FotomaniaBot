"""Рассылки и шаблоны сообщений."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from ..db import session_scope
from ..message_sets import (
    campaign_messages,
    clean_messages,
    dump_messages,
    own_messages,
    rebuild_task_messages,
    task_messages,
)
from ..models import (
    Campaign,
    Client,
    DeliveryTask,
    MessageTemplate,
    School,
    SchoolClass,
    now,
)
from ..schemas import (
    CampaignDeleteIn,
    CampaignIn,
    CampaignMessagesIn,
)
from ..services import (
    render_message,
)
from ..worker import worker_wake

log = logging.getLogger("fotomaniabot")
router = APIRouter()


def _resolve_role_messages(plural: list[str] | None, single: str | None) -> list[str]:
    """Список текстов роли из нового поля-списка или из прежнего одиночного поля."""
    if plural is not None:
        items = plural
    elif single is not None and single.strip():
        items = [single]
    else:
        items = []
    try:
        return clean_messages(items)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _apply_messages(campaign: Campaign, kr: list[str], rk: list[str], generic: str = "") -> None:
    """Сохраняет наборы текстов и зеркалит первые тексты в прежние поля."""
    campaign.messages_kr = dump_messages(kr)
    campaign.messages_rk = dump_messages(rk)
    campaign.message_kr = kr[0] if kr else None
    campaign.message_rk = rk[0] if rk else None
    campaign.message = (kr or rk or [generic])[0]


def _fill_task(task: DeliveryTask, campaign: Campaign, contact: Client) -> bool:
    """Пересобирает сообщения задания из шаблонов рассылки."""
    texts = [render_message(t, contact) for t in campaign_messages(campaign, contact.role)]
    return rebuild_task_messages(task, texts)


MESSAGE_EDITABLE_STATUSES = frozenset(
    {"PENDING", "REQUIRES_REVIEW", "CONTACT_NOT_FOUND", "MAX_ERROR"}
)
MESSAGE_ROLES = frozenset({"KR", "RK"})
MAX_TEMPLATES_PER_ROLE = 100


def _remember_template(session: Any, role: str, body: str | None) -> None:
    """Сохраняет использованный текст рассылки для роли; дубликаты не создаются."""
    text = (body or "").strip()
    if not text:
        return
    template = session.scalar(
        select(MessageTemplate).where(MessageTemplate.role == role, MessageTemplate.body == text)
    )
    if template is None:
        session.add(MessageTemplate(role=role, body=text))
    else:
        template.updated_at = now()


def template_dict(template: MessageTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "role": template.role,
        "body": template.body,
        "updated_at": template.updated_at,
    }


def status_counts(session: Any, campaign_ids: list[int]) -> dict[int, dict[str, int]]:
    """Число заданий по статусам для каждой рассылки — одним запросом."""
    counts: dict[int, dict[str, int]] = {campaign_id: {} for campaign_id in campaign_ids}
    if not campaign_ids:
        return counts
    rows = session.execute(
        select(DeliveryTask.campaign_id, DeliveryTask.status, func.count())
        .where(DeliveryTask.campaign_id.in_(campaign_ids))
        .group_by(DeliveryTask.campaign_id, DeliveryTask.status)
    ).all()
    for campaign_id, status, count in rows:
        counts[campaign_id][status] = count
    return counts


def campaign_dict(campaign: Campaign, statuses: dict[str, int]) -> dict[str, Any]:
    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "message": campaign.message,
        "message_kr": campaign.message_kr,
        "message_rk": campaign.message_rk,
        "messages_kr": own_messages(campaign, "KR"),
        "messages_rk": own_messages(campaign, "RK"),
        "school_id": campaign.school_id,
        "mode": campaign.mode,
        "status": campaign.status,
        "created_at": campaign.created_at,
        "started_at": campaign.started_at,
        "finished_at": campaign.finished_at,
        "stop_reason": campaign.stop_reason,
        "task_count": sum(statuses.values()),
        "status_counts": statuses,
    }


def task_dict(
    task: DeliveryTask, contact: Client, school_name: str, class_name: str
) -> dict[str, Any]:
    return {
        "id": task.id,
        "campaign_id": task.campaign_id,
        "client_id": task.client_id,
        "client": contact.name,
        "phone": contact.phone,
        "chat_link": contact.chat_link,
        "max_user_id": contact.max_user_id,
        "username": contact.username,
        "role": contact.role,
        "recipient_role": task.recipient_role,
        "school": school_name,
        "class_name": class_name,
        "message": task.rendered_message,
        "messages": [
            {"index": number, "text": item["text"], "prepared_at": item["prepared_at"]}
            for number, item in enumerate(task_messages(task), start=1)
        ],
        "status": task.status,
        "attempts": task.attempts,
        "error": task.error,
        "requires_review": task.requires_review,
        "opened_at": task.opened_at,
        "operator_confirmed_at": task.operator_confirmed_at,
        "operator_result": task.operator_result,
        "browser_prepared_at": task.browser_prepared_at,
        "browser_error": task.browser_error,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def load_campaign_tasks(
    session: Any, campaign_id: int, since: datetime | None = None
) -> list[dict[str, Any]]:
    """Задания рассылки; с `since` — только изменённые не раньше этого момента (UTC)."""
    statement = (
        select(DeliveryTask, Client, School.name, SchoolClass.name)
        .join(Client, Client.id == DeliveryTask.client_id)
        .outerjoin(SchoolClass, SchoolClass.id == Client.class_id)
        .outerjoin(School, School.id == Client.school_id)
        .where(DeliveryTask.campaign_id == campaign_id)
        .order_by(DeliveryTask.id)
    )
    if since is not None:
        statement = statement.where(DeliveryTask.updated_at >= since)
    rows = session.execute(statement).all()
    return [
        task_dict(task, contact, school_name or "", class_name or "")
        for task, contact, school_name, class_name in rows
    ]


@router.get("/api/campaigns")
def list_campaigns() -> list[dict[str, Any]]:
    with session_scope() as session:
        campaigns = session.scalars(select(Campaign).order_by(Campaign.id.desc())).all()
        counts = status_counts(session, [campaign.id for campaign in campaigns])
        return [campaign_dict(campaign, counts[campaign.id]) for campaign in campaigns]


@router.post("/api/campaigns")
def create_campaign(data: CampaignIn) -> dict[str, Any]:
    client_ids = list(dict.fromkeys(data.client_ids))
    if not client_ids:
        raise HTTPException(400, "Не выбраны получатели")
    messages_kr = _resolve_role_messages(data.messages_kr, data.message_kr)
    messages_rk = _resolve_role_messages(data.messages_rk, data.message_rk)
    with session_scope() as session:
        contacts = session.scalars(select(Client).where(Client.id.in_(client_ids))).all()
        if len(contacts) != len(client_ids):
            raise HTTPException(404, "Некоторые получатели не найдены")
        if data.school_id is not None and session.get(School, data.school_id) is None:
            raise HTTPException(400, "Школа не найдена")
        campaign = Campaign(
            name=data.name.strip(),
            description=data.description,
            message=data.message,
            school_id=data.school_id,
            mode="manual",
            status="DRAFT",
        )
        _apply_messages(campaign, messages_kr, messages_rk, data.message.strip())
        session.add(campaign)
        session.flush()
        for contact in contacts:
            task = DeliveryTask(
                campaign_id=campaign.id,
                client_id=contact.id,
                recipient_role=contact.role,
                rendered_message="",
                status="PENDING",
            )
            _fill_task(task, campaign, contact)
            session.add(task)
        for text in messages_kr:
            _remember_template(session, "KR", text)
        for text in messages_rk:
            _remember_template(session, "RK", text)
        session.commit()
        session.refresh(campaign)
        return campaign_dict(campaign, status_counts(session, [campaign.id])[campaign.id])


@router.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: int) -> dict[str, Any]:
    with session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(404, "Кампания не найдена")
        return campaign_dict(campaign, status_counts(session, [campaign_id])[campaign_id])


@router.get("/api/campaigns/{campaign_id}/tasks")
def campaign_tasks(campaign_id: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        return load_campaign_tasks(session, campaign_id)


# Запас на транзакции, которые записали updated_at раньше, чем стали видны другим запросам.
CHANGES_CURSOR_OVERLAP = timedelta(seconds=5)


@router.get("/api/campaigns/{campaign_id}/tasks/changes")
def campaign_task_changes(campaign_id: int, since: datetime | None = None) -> dict[str, Any]:
    """Изменившиеся с `since` задания, список всех id (для удалений) и новый курсор.

    Без `since` возвращаются все задания. Клиент хранит `cursor` и передаёт его
    в следующий запрос: при отсутствии изменений ответ почти пустой.
    """
    if since is not None:
        since = (
            since.astimezone(timezone.utc) if since.tzinfo else since.replace(tzinfo=timezone.utc)
        )
    cursor = now() - CHANGES_CURSOR_OVERLAP
    with session_scope() as session:
        if session.get(Campaign, campaign_id) is None:
            raise HTTPException(404, "Кампания не найдена")
        changed = load_campaign_tasks(session, campaign_id, since)
        ids = session.scalars(
            select(DeliveryTask.id)
            .where(DeliveryTask.campaign_id == campaign_id)
            .order_by(DeliveryTask.id)
        ).all()
    return {"changed": changed, "ids": list(ids), "cursor": cursor.isoformat()}


@router.post("/api/campaigns/{campaign_id}/start")
def start_campaign(campaign_id: int) -> dict[str, Any]:
    with session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(404, "Кампания не найдена")
        if campaign.status == "RUNNING":
            return {"status": "running"}
        campaign.status = "RUNNING"
        campaign.started_at = now()
        campaign.finished_at = None
        session.commit()
    worker_wake.set()
    return {"status": "running"}


@router.post("/api/campaigns/{campaign_id}/stop")
def stop_campaign(campaign_id: int, reason: str = "") -> dict[str, Any]:
    with session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(404, "Кампания не найдена")
        campaign.status = "STOPPED"
        campaign.finished_at = now()
        campaign.stop_reason = reason or "Остановлено оператором"
        session.commit()
    return {"status": "stopped"}


@router.delete("/api/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int) -> dict[str, str]:
    with session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(404, "Кампания не найдена")
        session.query(DeliveryTask).filter(DeliveryTask.campaign_id == campaign_id).delete(
            synchronize_session=False
        )
        session.delete(campaign)
        session.commit()
    return {"status": "deleted"}


@router.post("/api/campaigns/delete")
def delete_campaigns(data: CampaignDeleteIn) -> dict[str, int]:
    campaign_ids = list(dict.fromkeys(data.campaign_ids))
    with session_scope() as session:
        existing_ids = session.scalars(
            select(Campaign.id).where(Campaign.id.in_(campaign_ids))
        ).all()
        if not existing_ids:
            raise HTTPException(404, "Выбранные кампании не найдены")
        session.query(DeliveryTask).filter(DeliveryTask.campaign_id.in_(existing_ids)).delete(
            synchronize_session=False
        )
        deleted = (
            session.query(Campaign)
            .filter(Campaign.id.in_(existing_ids))
            .delete(synchronize_session=False)
        )
        session.commit()
    return {"deleted": deleted}


@router.get("/api/message-templates/{role}")
def list_message_templates(role: str) -> list[dict[str, Any]]:
    if role not in MESSAGE_ROLES:
        raise HTTPException(400, "Роль должна быть KR или RK")
    with session_scope() as session:
        templates = session.scalars(
            select(MessageTemplate)
            .where(MessageTemplate.role == role)
            .order_by(MessageTemplate.updated_at.desc(), MessageTemplate.id.desc())
            .limit(MAX_TEMPLATES_PER_ROLE)
        ).all()
        return [template_dict(item) for item in templates]


@router.patch("/api/campaigns/{campaign_id}/messages")
def update_campaign_messages(campaign_id: int, data: CampaignMessagesIn) -> dict[str, Any]:
    message_kr = _resolve_role_messages(data.messages_kr, data.message_kr)
    message_rk = _resolve_role_messages(data.messages_rk, data.message_rk)
    if not message_kr and not message_rk:
        raise HTTPException(422, "Укажите текст хотя бы для одной роли")
    with session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(404, "Кампания не найдена")
        _apply_messages(campaign, message_kr, message_rk)
        for text in message_kr:
            _remember_template(session, "KR", text)
        for text in message_rk:
            _remember_template(session, "RK", text)
        rows = session.execute(
            select(DeliveryTask, Client)
            .join(Client, Client.id == DeliveryTask.client_id)
            .where(DeliveryTask.campaign_id == campaign_id)
        ).all()
        updated = skipped = 0
        for task, contact in rows:
            if task.status not in MESSAGE_EDITABLE_STATUSES:
                skipped += 1
                continue
            if _fill_task(task, campaign, contact):
                updated += 1
        session.commit()
        return {
            "updated": updated,
            "skipped": skipped,
            "campaign": campaign_dict(campaign, status_counts(session, [campaign_id])[campaign_id]),
        }
