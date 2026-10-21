"""CSV-отчёты по рассылкам."""

from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..db import session_scope
from ..models import (
    Campaign,
)
from ..services import (
    csv_safe,
)
from .campaigns import load_campaign_tasks

log = logging.getLogger("fotomaniabot")
router = APIRouter()


@router.get("/api/reports/{campaign_id}/export")
def export_report(campaign_id: int) -> StreamingResponse:
    with session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(404, "Кампания не найдена")
        header = [
            "Кампания",
            "ФИО",
            "Телефон",
            "Роль",
            "Школа",
            "Класс",
            "Статус",
            "Результат оператора",
            "Попыток",
            "Ошибка",
            "Подготовлено",
            "Сообщений подготовлено",
            "Подтверждено",
        ]
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        writer.writerow(header)
        for item in load_campaign_tasks(session, campaign_id):
            writer.writerow(
                [
                    csv_safe(campaign.name),
                    csv_safe(item["client"]),
                    csv_safe(item["phone"]),
                    csv_safe(item["recipient_role"]),
                    csv_safe(item["school"]),
                    csv_safe(item["class_name"]),
                    csv_safe(item["status"]),
                    csv_safe(item["operator_result"]),
                    csv_safe(item["attempts"]),
                    csv_safe(item["error"]),
                    csv_safe(item["browser_prepared_at"]),
                    csv_safe(
                        f"{sum(1 for m in item['messages'] if m['prepared_at'])}"
                        f" из {len(item['messages'])}"
                    ),
                    csv_safe(item["operator_confirmed_at"]),
                ]
            )
        payload = "\ufeff" + buffer.getvalue()
    filename = f"campaign-{campaign_id}-report.csv"
    return StreamingResponse(
        iter([payload.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
