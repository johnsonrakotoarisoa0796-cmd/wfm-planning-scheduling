"""Imports opérationnels CSV/Excel vers ActualPerformanceRaw et Intraday."""
from __future__ import annotations

from datetime import datetime, time
from io import BytesIO
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_role, verify_csrf
from app.core.templating import templates
from app.models.intraday import ActualPerformanceRaw, IntervalForecast
from app.models.client_stf import ClientSTFPlan, ClientSTFInterval
from app.models.enums import UserRole
from app.models.user import User
from app.models.skill import Skill
from app.services import channel_service, intraday_service

router = APIRouter(prefix="/imports", tags=["imports"])
WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST, UserRole.TEAM_LEAD)

REQUIRED_COLUMNS = {
    "date", "interval_start", "campaign_id", "skill_id",
    "offered", "handled", "abandoned", "talk_time_seconds",
    "hold_time_seconds", "acw_seconds", "agents_staffed", "paid_hours",
}
OPTIONAL_COLUMNS = {"answered_within_threshold"}


def _as_time(value) -> time:
    if isinstance(value, time):
        return value
    text = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Heure invalide: {value}")


def _load_dataframe(filename: str, content: bytes) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return pd.read_excel(BytesIO(content))
    return pd.read_csv(BytesIO(content))


@router.get("")
def import_page(
    request: Request,
    current_user: User = Depends(require_role(*WRITE_ROLES)),
):
    return templates.TemplateResponse(
        request,
        "imports/index.html",
        {"active_nav": "imports", "current_user": current_user, "errors": [], "result": None},
    )


@router.post("/actuals", dependencies=[Depends(verify_csrf)])
async def import_actuals(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    try:
        content = await file.read()
        frame = _load_dataframe(file.filename or "actuals.csv", content)
        frame.columns = [str(column).strip() for column in frame.columns]
        missing = REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise ValueError("Colonnes manquantes: " + ", ".join(sorted(missing)))
        batch_id = str(uuid4())
        imported = 0
        matched = 0

        for _, raw in frame.iterrows():
            day = pd.to_datetime(raw["date"]).date()
            interval_start = _as_time(raw["interval_start"])
            handled = float(raw["handled"] or 0)
            talk = float(raw["talk_time_seconds"] or 0)
            hold = float(raw["hold_time_seconds"] or 0)
            acw = float(raw["acw_seconds"] or 0)
            offered = float(raw["offered"] or 0)
            abandoned = float(raw["abandoned"] or 0)
            answered_raw = raw.get("answered_within_threshold")
            answered_within_threshold = (
                float(answered_raw) if pd.notna(answered_raw) and str(answered_raw).strip() else None
            )
            if answered_within_threshold is not None and (
                answered_within_threshold < 0 or answered_within_threshold > offered
            ):
                raise ValueError(
                    f"Ligne {int(getattr(raw, 'name', 0)) + 2}: answered_within_threshold doit être "
                    "compris entre 0 et offered."
                )
            agents = float(raw["agents_staffed"] or 0)
            campaign_id = int(raw["campaign_id"])
            skill_id = int(raw["skill_id"])

            session.add(
                ActualPerformanceRaw(
                    date=day,
                    interval_start=interval_start,
                    campaign_id=campaign_id,
                    skill_id=skill_id,
                    offered=offered,
                    handled=handled,
                    abandoned=abandoned,
                    answered_within_threshold=answered_within_threshold,
                    talk_time_seconds=talk,
                    hold_time_seconds=hold,
                    acw_seconds=acw,
                    agents_staffed=agents,
                    paid_hours=float(raw["paid_hours"] or 0),
                    import_batch_id=batch_id,
                )
            )

            interval = session.exec(
                select(IntervalForecast).where(
                    IntervalForecast.date == day,
                    IntervalForecast.interval_start == interval_start,
                    IntervalForecast.campaign_id == campaign_id,
                    IntervalForecast.skill_id == skill_id,
                )
            ).first()
            if interval is not None:
                interval.actual_volume = offered
                interval.actual_aht_seconds = (
                    (talk + hold + acw) / handled if handled > 0 else None
                )
                interval.actual_hc = agents
                interval.abandon_rate_pct = (
                    abandoned / offered * 100.0 if offered > 0 else 0.0
                )
                if answered_within_threshold is not None and offered > 0:
                    eligible = max(0.0, offered)
                    interval.service_level_pct = (
                        answered_within_threshold / eligible * 100.0
                    )
                if interval.actual_hc and interval.actual_aht_seconds:
                    capacity_hours = interval.actual_hc * intraday_service.interval_duration_hours(interval.interval_start, interval.interval_end)
                    skill = session.get(Skill, skill_id)
                    if skill is None:
                        raise ValueError("Skill introuvable.")
                    workload_hours = channel_service.normalized_workload_hours(
                        offered,
                        interval.actual_aht_seconds,
                        interval.channel,
                        concurrency_factor=skill.concurrency_factor,
                    )
                    interval.occupancy_pct = workload_hours / capacity_hours * 100.0 if capacity_hours else 0.0
                    effective_required_hc = interval.required_hc
                    client_plan = session.exec(
                        select(ClientSTFPlan).where(
                            ClientSTFPlan.week_start_date
                            <= interval.date,
                            ClientSTFPlan.campaign_id == campaign_id,
                            ClientSTFPlan.skill_id == skill_id,
                            ClientSTFPlan.is_current == True,  # noqa: E712
                        )
                    ).first()
                    if client_plan is not None:
                        client_row = session.exec(
                            select(ClientSTFInterval).where(
                                ClientSTFInterval.plan_id == client_plan.id,
                                ClientSTFInterval.date == interval.date,
                                ClientSTFInterval.interval_start == interval.interval_start,
                            )
                        ).first()
                        if client_row is not None:
                            effective_required_hc = client_row.required_hc
                    interval.staffing_gap = interval.actual_hc - effective_required_hc
                session.add(interval)
                matched += 1
            imported += 1

        session.commit()
        result = {"batch_id": batch_id, "imported": imported, "matched": matched}
        return templates.TemplateResponse(
            request,
            "imports/index.html",
            {"active_nav": "imports", "current_user": current_user, "errors": [], "result": result},
        )
    except Exception as exc:
        session.rollback()
        return templates.TemplateResponse(
            request,
            "imports/index.html",
            {"active_nav": "imports", "current_user": current_user, "errors": [str(exc)], "result": None},
            status_code=400,
        )
