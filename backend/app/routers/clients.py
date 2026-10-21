"""Контакты (КР/РК)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..db import session_scope
from ..models import (
    Client,
    DeliveryTask,
    School,
    SchoolClass,
)
from ..phones import normalize_phone
from ..schemas import (
    ClientDeleteIn,
    ClientIn,
)
from ..services import (
    client_dict,
)

log = logging.getLogger("fotomaniabot")
router = APIRouter()

DUPLICATE_FIELDS = ("max_user_id", "username", "chat_link")


@router.get("/api/clients")
def list_clients(
    q: str = "",
    opted_out: bool | None = None,
    school_id: int | None = None,
    class_id: int | None = None,
) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = select(Client).order_by(Client.id.desc())
        if q:
            query = query.where(Client.name.ilike(f"%{q}%"))
        if opted_out is not None:
            query = query.where(Client.opted_out == opted_out)
        if school_id is not None:
            query = query.where(Client.school_id == school_id)
        if class_id is not None:
            query = query.where(Client.class_id == class_id)
        return [client_dict(c) for c in session.scalars(query).all()]


def _validate_client_links(session: Any, school_id: int | None, class_id: int | None) -> None:
    if school_id is not None and session.get(School, school_id) is None:
        raise HTTPException(400, "Школа не найдена")
    if class_id is not None and session.get(SchoolClass, class_id) is None:
        raise HTTPException(400, "Класс не найден")
    if class_id is not None and school_id is not None:
        class_item = session.get(SchoolClass, class_id)
        if class_item and class_item.school_id != school_id:
            raise HTTPException(400, "Класс не относится к выбранной школе")


def find_client_duplicate(session: Any, values: dict[str, Any]) -> Client | None:
    from sqlalchemy import or_

    conditions = [
        getattr(Client, key) == values[key] for key in DUPLICATE_FIELDS if values.get(key)
    ]
    if not conditions:
        return None
    return session.scalar(select(Client).where(or_(*conditions)))


@router.post("/api/clients")
def create_client(data: ClientIn) -> dict[str, Any]:
    if data.role not in {"KR", "RK"}:
        raise HTTPException(400, "Роль должна быть KR или RK")
    with session_scope() as session:
        _validate_client_links(session, data.school_id, data.class_id)
        if find_client_duplicate(session, data.model_dump()) is not None:
            raise HTTPException(409, "Клиент с таким идентификатором уже существует")
        payload = data.model_dump(exclude={"custom_fields"})
        payload["phone"] = normalize_phone(payload.get("phone"))
        c = Client(**payload, custom_fields=json.dumps(data.custom_fields, ensure_ascii=False))
        session.add(c)
        session.commit()
        session.refresh(c)
        return client_dict(c)


@router.patch("/api/clients/{client_id}")
def update_client(client_id: int, data: ClientIn) -> dict[str, Any]:
    with session_scope() as session:
        c = session.get(Client, client_id)
        if c is None:
            raise HTTPException(404, "Клиент не найден")
        _validate_client_links(session, data.school_id, data.class_id)
        for key, value in data.model_dump(exclude={"custom_fields"}).items():
            setattr(c, key, normalize_phone(value) if key == "phone" else value)
        c.custom_fields = json.dumps(data.custom_fields, ensure_ascii=False)
        session.commit()
        return client_dict(c)


@router.delete("/api/clients/{client_id}")
def delete_client(client_id: int) -> dict[str, str]:
    with session_scope() as session:
        c = session.get(Client, client_id)
        if c is None:
            raise HTTPException(404, "Клиент не найден")
        session.query(DeliveryTask).filter(DeliveryTask.client_id == client_id).delete(
            synchronize_session=False
        )
        session.delete(c)
        session.commit()
    return {"status": "deleted"}


@router.post("/api/clients/delete")
def delete_clients(data: ClientDeleteIn) -> dict[str, int]:
    client_ids = list(dict.fromkeys(data.client_ids))
    with session_scope() as session:
        existing_ids = session.scalars(select(Client.id).where(Client.id.in_(client_ids))).all()
        if not existing_ids:
            raise HTTPException(404, "Выбранные контакты не найдены")
        session.query(DeliveryTask).filter(DeliveryTask.client_id.in_(existing_ids)).delete(
            synchronize_session=False
        )
        deleted = (
            session.query(Client)
            .filter(Client.id.in_(existing_ids))
            .delete(synchronize_session=False)
        )
        session.commit()
    return {"deleted": deleted}
