"""Service Workforce global par campagne."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.time_utils import utc_now
from app.models.campaign import Campaign
from app.models.campaign_workforce import CampaignWorkforcePlan
from app.models.employee import Employee
from app.models.enums import EmployeeStatus
from app.schemas.campaign_workforce import CampaignWorkforcePlanInput

settings = get_settings()


@dataclass(frozen=True)
class WorkforceMetrics:
    attrition_hc: float
    projected_hc: float
    production_available_hc: float
    availability_pct: float
    projected_production_hc: float
    projected_gap_hc: float


@dataclass(frozen=True)
class WorkforceRosterSnapshot:
    active_roster_hc: int
    active_roster_fte: float


def _validate_business_values(data: CampaignWorkforcePlanInput) -> None:
    if data.available_hc > data.current_hc:
        raise ValueError("Les agents disponibles ne peuvent pas dépasser le Current HC.")
    if data.long_leave_hc + data.training_hc + data.nesting_hc + data.other_unavailable_hc > data.current_hc:
        raise ValueError(
            "La somme des indisponibilités ne peut pas dépasser le Current HC."
        )


def calculate_metrics(plan: CampaignWorkforcePlan) -> WorkforceMetrics:
    attrition_hc = min(
        plan.current_hc,
        max(0.0, plan.current_hc * plan.attrition_pct / 100.0),
    )
    projected_hc = max(
        0.0,
        plan.current_hc
        + plan.hiring_hc
        + plan.transfers_in_hc
        - plan.transfers_out_hc
        - attrition_hc,
    )
    production_available_hc = max(
        0.0,
        plan.available_hc
        - plan.training_hc
        - plan.nesting_hc
        - plan.other_unavailable_hc,
    )
    availability_pct = (
        production_available_hc / plan.current_hc * 100.0
        if plan.current_hc > 0
        else 0.0
    )
    projected_production_hc = max(
        0.0,
        projected_hc
        - plan.long_leave_hc
        - plan.training_hc
        - plan.nesting_hc
        - plan.other_unavailable_hc,
    )
    projected_gap_hc = projected_production_hc - plan.required_hc
    return WorkforceMetrics(
        attrition_hc=attrition_hc,
        projected_hc=projected_hc,
        production_available_hc=production_available_hc,
        availability_pct=availability_pct,
        projected_production_hc=projected_production_hc,
        projected_gap_hc=projected_gap_hc,
    )


def roster_snapshot(
    session: Session,
    *,
    campaign_id: int,
    period: str,
) -> WorkforceRosterSnapshot:
    year, month = (int(part) for part in period.split("-"))
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    rows = list(
        session.exec(
            select(Employee)
            .where(Employee.campaign_id == campaign_id)
            .where(Employee.status == EmployeeStatus.ACTIVE)
            .where(Employee.hire_date <= month_end)
            .where(
                (Employee.termination_date.is_(None))
                | (Employee.termination_date >= month_start)
            )
        ).all()
    )
    weekly_hours = max(float(settings.weekly_hours), 1.0)
    return WorkforceRosterSnapshot(
        active_roster_hc=len(rows),
        active_roster_fte=sum(
            max(0.0, employee.weekly_hours_contract) / weekly_hours
            for employee in rows
        ),
    )


def get_plan(
    session: Session,
    *,
    campaign_id: int,
    period: str,
) -> Optional[CampaignWorkforcePlan]:
    return session.exec(
        select(CampaignWorkforcePlan).where(
            CampaignWorkforcePlan.campaign_id == campaign_id,
            CampaignWorkforcePlan.period == period,
        )
    ).first()


def upsert_plan(
    session: Session,
    data: CampaignWorkforcePlanInput,
    *,
    created_by_user_id: int | None,
) -> CampaignWorkforcePlan:
    _validate_business_values(data)

    campaign = session.get(Campaign, data.campaign_id)
    if campaign is None or not campaign.is_active:
        raise ValueError("La campagne sélectionnée est introuvable ou inactive.")

    plan = get_plan(session, campaign_id=data.campaign_id, period=data.period)
    if plan is None:
        plan = CampaignWorkforcePlan(
            campaign_id=data.campaign_id,
            period=data.period,
            created_by=created_by_user_id,
        )

    plan.current_hc = data.current_hc
    plan.available_hc = data.available_hc
    plan.long_leave_hc = data.long_leave_hc
    plan.training_hc = data.training_hc
    plan.nesting_hc = data.nesting_hc
    plan.other_unavailable_hc = data.other_unavailable_hc
    plan.attrition_pct = data.attrition_pct
    plan.hiring_hc = data.hiring_hc
    plan.transfers_in_hc = data.transfers_in_hc
    plan.transfers_out_hc = data.transfers_out_hc
    plan.required_hc = data.required_hc
    plan.notes = data.notes.strip() or None if data.notes else None
    plan.updated_at = utc_now()

    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan
