"""Школы и классы."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db import session_scope
from ..models import (
    Campaign,
    Client,
    DeliveryTask,
    School,
    SchoolClass,
)
from ..schemas import (
    ClassIn,
    ClassUpdateIn,
    SchoolUpdateIn,
)

log = logging.getLogger("fotomaniabot")
router = APIRouter()


@router.get("/api/schools")
def list_schools() -> list[dict[str, Any]]:
    with session_scope() as session:
        # Три запроса на всё дерево «школа → класс → контакты» вместо запроса на каждый класс.
        schools = session.scalars(select(School).order_by(School.name)).all()
        classes = session.scalars(select(SchoolClass).order_by(SchoolClass.name)).all()
        contacts = session.scalars(
            select(Client).where(Client.class_id.is_not(None)).order_by(Client.role, Client.name)
        ).all()
        contacts_by_class: dict[int, list[dict[str, Any]]] = {}
        for contact in contacts:
            contacts_by_class.setdefault(contact.class_id, []).append(
                {
                    "id": contact.id,
                    "name": contact.name,
                    "phone": contact.phone,
                    "role": contact.role,
                    "opted_out": contact.opted_out,
                }
            )
        classes_by_school: dict[int, list[dict[str, Any]]] = {}
        for item in classes:
            classes_by_school.setdefault(item.school_id, []).append(
                {"id": item.id, "name": item.name, "contacts": contacts_by_class.get(item.id, [])}
            )
        return [
            {"id": school.id, "name": school.name, "classes": classes_by_school.get(school.id, [])}
            for school in schools
        ]


@router.post("/api/classes")
def create_class(data: ClassIn) -> dict[str, Any]:
    school_name = data.school_name.strip()
    class_name = data.class_name.strip()
    with session_scope() as session:
        school = session.scalar(select(School).where(School.name == school_name))
        if school is None:
            school = School(name=school_name)
            session.add(school)
            session.flush()
        existing = session.scalar(
            select(SchoolClass).where(
                SchoolClass.school_id == school.id, SchoolClass.name == class_name
            )
        )
        if existing:
            return {"school_id": school.id, "class_id": existing.id, "status": "existing"}
        item = SchoolClass(school_id=school.id, name=class_name)
        session.add(item)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "Такой класс уже существует в этой школе") from exc
        return {"school_id": school.id, "class_id": item.id, "status": "created"}


@router.patch("/api/schools/{school_id}")
def update_school(school_id: int, data: SchoolUpdateIn) -> dict[str, Any]:
    with session_scope() as session:
        school = session.get(School, school_id)
        if school is None:
            raise HTTPException(404, "Школа не найдена")
        name = data.name.strip()
        duplicate = session.scalar(
            select(School).where(School.name == name, School.id != school_id)
        )
        if duplicate:
            raise HTTPException(409, "Школа с таким названием уже существует")
        school.name = name
        session.commit()
        return {"id": school.id, "name": school.name}


@router.delete("/api/schools/{school_id}")
def delete_school(school_id: int) -> dict[str, str]:
    with session_scope() as session:
        school = session.get(School, school_id)
        if school is None:
            raise HTTPException(404, "Школа не найдена")
        class_ids = session.scalars(
            select(SchoolClass.id).where(SchoolClass.school_id == school_id)
        ).all()
        client_filter = Client.school_id == school_id
        if class_ids:
            client_filter = client_filter | Client.class_id.in_(class_ids)
        client_ids = session.scalars(select(Client.id).where(client_filter)).all()
        if client_ids:
            session.query(DeliveryTask).filter(DeliveryTask.client_id.in_(client_ids)).delete(
                synchronize_session=False
            )
            session.query(Client).filter(Client.id.in_(client_ids)).delete(
                synchronize_session=False
            )
        if class_ids:
            session.query(SchoolClass).filter(SchoolClass.id.in_(class_ids)).delete(
                synchronize_session=False
            )
        # В базах, созданных старыми миграциями, внешние ключи без каскадов: рассылки школы
        # остаются, но привязку к ней снимаем вручную, иначе удаление упадёт на FOREIGN KEY.
        session.query(Campaign).filter(Campaign.school_id == school_id).update(
            {Campaign.school_id: None}, synchronize_session=False
        )
        session.delete(school)
        session.commit()
    return {"status": "deleted"}


@router.patch("/api/classes/{class_id}")
def update_class(class_id: int, data: ClassUpdateIn) -> dict[str, Any]:
    with session_scope() as session:
        item = session.get(SchoolClass, class_id)
        if item is None:
            raise HTTPException(404, "Класс не найден")
        duplicate = session.scalar(
            select(SchoolClass).where(
                SchoolClass.school_id == item.school_id,
                SchoolClass.name == data.name.strip(),
                SchoolClass.id != class_id,
            )
        )
        if duplicate:
            raise HTTPException(409, "Такой класс уже существует в этой школе")
        item.name = data.name.strip()
        session.commit()
        return {"id": item.id, "school_id": item.school_id, "name": item.name}


@router.delete("/api/classes/{class_id}")
def delete_class(class_id: int) -> dict[str, str]:
    with session_scope() as session:
        item = session.get(SchoolClass, class_id)
        if item is None:
            raise HTTPException(404, "Класс не найден")
        client_ids = session.scalars(select(Client.id).where(Client.class_id == class_id)).all()
        if client_ids:
            session.query(DeliveryTask).filter(DeliveryTask.client_id.in_(client_ids)).delete(
                synchronize_session=False
            )
            session.query(Client).filter(Client.id.in_(client_ids)).delete(
                synchronize_session=False
            )
        session.delete(item)
        session.commit()
    return {"status": "deleted"}
