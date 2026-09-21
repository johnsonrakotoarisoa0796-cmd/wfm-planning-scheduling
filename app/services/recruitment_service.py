"""Moteur de recrutement et de ramp-up."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from app.models.recruitment import RecruitmentPlan, RecruitmentRampWeek


@dataclass(frozen=True)
class RampWeekProjection:
    week: RecruitmentRampWeek
    paid_hours: float
    staffed_capacity_hours: float
    capacity_contacts: float


def create_recruitment_plan(
    session: Session,
    *,
    cohort_name: str,
    campaign_id: int,
    skill_id: int,
    start_date: date,
    headcount: int,
    weekly_hours_contract: float,
    training_weeks: int,
    nesting_weeks: int,
    training_aht_seconds: float,
    training_occupancy_pct: float,
    nesting_aht_seconds: float,
    nesting_occupancy_pct: float,
    nesting_capacity_factor_pct: float,
    production_aht_seconds: float,
    production_occupancy_pct: float,
    created_by: int | None,
    notes: str | None = None,
) -> RecruitmentPlan:
    if headcount <= 0:
        raise ValueError("Le headcount recruté doit être > 0.")
    if training_weeks < 0 or nesting_weeks < 0:
        raise ValueError("Les durées de formation/nesting doivent être >= 0.")
    if weekly_hours_contract <= 0:
        raise ValueError("Le contrat hebdomadaire doit être > 0.")
    for label, value in (
        ("AHT formation", training_aht_seconds),
        ("AHT nesting", nesting_aht_seconds),
        ("AHT production", production_aht_seconds),
    ):
        if value <= 0:
            raise ValueError(f"{label} doit être > 0.")
    for label, value in (
        ("occupancy formation", training_occupancy_pct),
        ("occupancy nesting", nesting_occupancy_pct),
        ("occupancy production", production_occupancy_pct),
        ("capacité nesting", nesting_capacity_factor_pct),
    ):
        if not 0 <= value <= 100:
            raise ValueError(f"{label} doit être compris entre 0 et 100%.")

    plan = RecruitmentPlan(
        cohort_name=cohort_name.strip(),
        campaign_id=campaign_id,
        skill_id=skill_id,
        start_date=start_date,
        headcount=headcount,
        weekly_hours_contract=weekly_hours_contract,
        training_weeks=training_weeks,
        nesting_weeks=nesting_weeks,
        notes=notes.strip() or None if notes else None,
        created_by=created_by,
        is_active=True,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)

    total_weeks = training_weeks + nesting_weeks + 1
    rows: list[RecruitmentRampWeek] = []
    for week_number in range(1, total_weeks + 1):
        if week_number <= training_weeks:
            stage, aht, occupancy, factor = (
                "training", training_aht_seconds, training_occupancy_pct, 0.0
            )
        elif week_number <= training_weeks + nesting_weeks:
            stage, aht, occupancy, factor = (
                "nesting", nesting_aht_seconds, nesting_occupancy_pct, nesting_capacity_factor_pct
            )
        else:
            stage, aht, occupancy, factor = (
                "production", production_aht_seconds, production_occupancy_pct, 100.0
            )
        rows.append(
            RecruitmentRampWeek(
                plan_id=plan.id,
                week_number=week_number,
                week_start_date=start_date + timedelta(days=7 * (week_number - 1)),
                stage=stage,
                aht_seconds=aht,
                occupancy_pct=occupancy,
                capacity_factor_pct=factor,
            )
        )
    session.add_all(rows)
    session.commit()
    return plan


def list_ramp_weeks(session: Session, plan_id: int) -> list[RecruitmentRampWeek]:
    return list(
        session.exec(
            select(RecruitmentRampWeek)
            .where(RecruitmentRampWeek.plan_id == plan_id)
            .order_by(RecruitmentRampWeek.week_number)
        ).all()
    )


def project_ramp(plan: RecruitmentPlan, weeks: list[RecruitmentRampWeek]) -> list[RampWeekProjection]:
    result: list[RampWeekProjection] = []
    for row in weeks:
        paid_hours = plan.headcount * plan.weekly_hours_contract
        staffed_capacity_hours = paid_hours * (row.capacity_factor_pct / 100.0) * (row.occupancy_pct / 100.0)
        capacity_contacts = staffed_capacity_hours * 3600.0 / row.aht_seconds if row.aht_seconds > 0 else 0.0
        result.append(
            RampWeekProjection(
                week=row,
                paid_hours=paid_hours,
                staffed_capacity_hours=staffed_capacity_hours,
                capacity_contacts=capacity_contacts,
            )
        )
    return result


@dataclass(frozen=True)
class RecruitmentProgressSnapshot:
    planned_hc: int
    recruited_hc: int
    training_hc: int
    nesting_hc: int
    production_hc: int
    exited_hc: int
    active_pipeline_hc: int
    production_readiness_pct: float
    recruitment_completion_pct: float
    current_stage: str
    expected_production_date: date


def progress_snapshot(plan: RecruitmentPlan) -> RecruitmentProgressSnapshot:
    expected_production_date = plan.start_date + timedelta(
        days=7 * (plan.training_weeks + plan.nesting_weeks)
    )
    active_pipeline_hc = max(0, plan.recruited_hc - plan.exited_hc)
    recruitment_completion_pct = (
        min(100.0, plan.recruited_hc / plan.headcount * 100.0)
        if plan.headcount
        else 0.0
    )
    production_readiness_pct = (
        min(100.0, plan.production_hc / plan.headcount * 100.0)
        if plan.headcount
        else 0.0
    )

    if plan.production_hc > 0 and plan.production_hc >= active_pipeline_hc and active_pipeline_hc > 0:
        current_stage = "production"
    elif plan.nesting_hc > 0:
        current_stage = "nesting"
    elif plan.training_hc > 0:
        current_stage = "training"
    elif plan.recruited_hc > 0:
        current_stage = "recruited"
    else:
        current_stage = "planned"

    return RecruitmentProgressSnapshot(
        planned_hc=plan.headcount,
        recruited_hc=plan.recruited_hc,
        training_hc=plan.training_hc,
        nesting_hc=plan.nesting_hc,
        production_hc=plan.production_hc,
        exited_hc=plan.exited_hc,
        active_pipeline_hc=active_pipeline_hc,
        production_readiness_pct=production_readiness_pct,
        recruitment_completion_pct=recruitment_completion_pct,
        current_stage=current_stage,
        expected_production_date=expected_production_date,
    )


def update_progress(
    session: Session,
    plan: RecruitmentPlan,
    *,
    recruited_hc: int,
    training_hc: int,
    nesting_hc: int,
    production_hc: int,
    exited_hc: int,
) -> RecruitmentPlan:
    values = {
        "recruited_hc": recruited_hc,
        "training_hc": training_hc,
        "nesting_hc": nesting_hc,
        "production_hc": production_hc,
        "exited_hc": exited_hc,
    }
    if any(value < 0 for value in values.values()):
        raise ValueError("Les effectifs de progression doivent être >= 0.")
    if recruited_hc > plan.headcount:
        raise ValueError("Le nombre recruté ne peut pas dépasser le headcount planifié.")
    if exited_hc > recruited_hc:
        raise ValueError("Les sorties ne peuvent pas dépasser les personnes recrutées.")
    active_pipeline_hc = recruited_hc - exited_hc
    if training_hc + nesting_hc + production_hc > active_pipeline_hc:
        raise ValueError(
            "Formation + nesting + production ne peuvent pas dépasser le pipeline actif."
        )

    plan.recruited_hc = recruited_hc
    plan.training_hc = training_hc
    plan.nesting_hc = nesting_hc
    plan.production_hc = production_hc
    plan.exited_hc = exited_hc
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan
