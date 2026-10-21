"""Школы и классы."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db import session_scope
from ..models import (
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
        schools = session.scalars(select(School).order_by(School.name)).all()
        result = []
        for school in schools:
            classes = session.scalars(
                select(SchoolClass)
                .where(SchoolClass.school_id == school.id)
                .order_by(SchoolClass.name)
            ).all()
            class_data = []
            for item in classes:
                contacts = session.scalars(
                    select(Client)
                    .where(Client.class_id == item.id)
                    .order_by(Client.role, Client.name)
                ).all()
                class_data.append(
                    {
                        "id": item.id,
                        "name": item.name,
                        "contacts": [
                            {
                                "id": contact.id,
                                "name": contact.name,
                                "phone": contact.phone,
                                "role": contact.role,
                                "opted_out": contact.opted_out,
                            }
                            for contact in contacts
                        ],
                    }
                )
            result.append({"id": school.id, "name": school.name, "classes": class_data})
        return result


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
def update_school(
    school_id: int, data: SchoolUpdateIn
) -> dict[str, Any]:
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
            session.query(DeliveryTask).filter(
                DeliveryTask.client_id.in_(client_ids)
            ).delete(synchronize_session=False)
            session.query(Client).filter(Client.id.in_(client_ids)).delete(
                synchronize_session=False
            )
        if class_ids:
            session.query(SchoolClass).filter(SchoolClass.id.in_(class_ids)).delete(
                synchronize_session=False
            )
        session.delete(school)
        session.commit()
    return {"status": "deleted"}



@router.patch("/api/classes/{class_id}")
def update_class(
    class_id: int, data: ClassUpdateIn
) -> dict[str, Any]:
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
        client_ids = session.scalars(
            select(Client.id).where(Client.class_id == class_id)
        ).all()
        if client_ids:
            session.query(DeliveryTask).filter(
                DeliveryTask.client_id.in_(client_ids)
            ).delete(synchronize_session=False)
            session.query(Client).filter(Client.id.in_(client_ids)).delete(
                synchronize_session=False
            )
        session.delete(item)
        session.commit()
    return {"status": "deleted"}
