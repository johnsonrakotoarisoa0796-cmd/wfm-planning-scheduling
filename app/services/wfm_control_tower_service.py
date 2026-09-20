"""Control Tower WFM : vue opérationnelle consolidée et simulation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models.campaign import Campaign
from app.models.campaign_workforce import CampaignWorkforcePlan
from app.models.employee import Employee, EmployeeAbsence, EmployeeSkill
from app.models.enums import EmployeeStatus
from app.models.forecast import LTFForecast
from app.models.intraday import IntervalForecast
from app.models.skill import Skill
from app.services import client_stf_service, forecast_service, intraday_service, overtime_service, planner_service
from app.services.campaign_workforce_service import WorkforceMetrics, calculate_metrics, roster_snapshot


@dataclass(frozen=True)
class IntervalControl:
    interval: IntervalForecast
    required_hc: float
    scheduled_hc: float
    actual_hc: Optional[float]
    staffing_gap: float
    coverage_pct: float
    run_rate_volume: Optional[float]
    run_rate_aht_seconds: Optional[float]
    status: str


@dataclass(frozen=True)
class ControlTowerData:
    target_date: date
    campaign: Campaign
    skill: Skill
    ltf: Optional[LTFForecast]
    intervals: list[IntervalControl]
    forecast_volume: float
    actual_volume: Optional[float]
    forecast_accuracy_pct: Optional[float]
    peak_required_hc: float
    peak_scheduled_hc: float
    peak_actual_hc: Optional[float]
    shortage_hc_hours: float
    surplus_hc_hours: float
    overtime_hours: float
    workforce_plan: Optional[CampaignWorkforcePlan]
    workforce_metrics: Optional[WorkforceMetrics]
    roster_hc: int
    recommendations: list[planner_service.ShiftRecommendation]
    generated_at: date


def _effective_intervals(session: Session, *, target_date: date, campaign_id: int, skill_id: int) -> list[IntervalForecast]:
    raw = intraday_service.list_intervals_for_day(
        session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )
    client_plan = client_stf_service.current_plan(
        session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )
    if client_plan is None:
        return raw
    return client_stf_service.effective_intervals(raw, client_stf_service.list_intervals(session, client_plan.id))


def _latest_workforce_plan(session: Session, campaign_id: int, target_date: date) -> Optional[CampaignWorkforcePlan]:
    period = f"{target_date.year:04d}-{target_date.month:02d}"
    return session.exec(
        select(CampaignWorkforcePlan).where(
            CampaignWorkforcePlan.campaign_id == campaign_id,
            CampaignWorkforcePlan.period == period,
        )
    ).first()


def build_control_tower(
    session: Session,
    *,
    target_date: date,
    campaign_id: int,
    skill_id: int,
) -> ControlTowerData:
    campaign = session.get(Campaign, campaign_id)
    skill = session.get(Skill, skill_id)
    if campaign is None or skill is None or skill.campaign_id != campaign_id:
        raise ValueError("Campagne ou skill introuvable.")

    iso = target_date.isocalendar()
    ltf = forecast_service.get_current_weekly_ltf_forecast(
        session,
        iso_year=iso.year,
        iso_week=iso.week,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    if ltf is None:
        ltf = forecast_service.get_current_ltf_forecast(
            session,
            year=target_date.year,
            month=target_date.month,
            campaign_id=campaign_id,
            skill_id=skill_id,
        )

    intervals = _effective_intervals(
        session, target_date=target_date, campaign_id=campaign_id, skill_id=skill_id
    )

    controls: list[IntervalControl] = []
    for row in intervals:
        actual_hc = row.actual_hc
        scheduled_hc = row.scheduled_hc
        gap_basis = actual_hc if actual_hc is not None else scheduled_hc
        gap = gap_basis - row.required_hc
        coverage = min(100.0, gap_basis / row.required_hc * 100.0) if row.required_hc > 0 else 100.0
        run_rate_volume = row.actual_volume
        run_rate_aht = row.actual_aht_seconds
        if gap < -0.05:
            status = "critical"
        elif gap < 0.0:
            status = "warning"
        elif gap > 0.5:
            status = "surplus"
        else:
            status = "balanced"
        controls.append(
            IntervalControl(
                interval=row,
                required_hc=row.required_hc,
                scheduled_hc=scheduled_hc,
                actual_hc=actual_hc,
                staffing_gap=gap,
                coverage_pct=coverage,
                run_rate_volume=run_rate_volume,
                run_rate_aht_seconds=run_rate_aht,
                status=status,
            )
        )

    forecast_volume = sum(row.forecast_volume for row in intervals)
    actual_points = [(row.actual_volume, 1.0) for row in intervals if row.actual_volume is not None]
    actual_volume = sum(value for value, _ in actual_points) if actual_points else None
    accuracy = (
        max(0.0, 100.0 - abs(forecast_volume - actual_volume) / actual_volume * 100.0)
        if actual_volume and actual_volume > 0
        else None
    )
    peak_required = max((row.required_hc for row in intervals), default=0.0)
    peak_scheduled = max((row.scheduled_hc for row in intervals), default=0.0)
    actual_hcs = [row.actual_hc for row in intervals if row.actual_hc is not None]
    peak_actual = max(actual_hcs) if actual_hcs else None

    shortage_h = sum(
        max(row.required_hc - (row.actual_hc if row.actual_hc is not None else row.scheduled_hc), 0.0)
        * intraday_service.interval_duration_hours(row.interval_start, row.interval_end)
        for row in intervals
    )
    surplus_h = sum(
        max((row.actual_hc if row.actual_hc is not None else row.scheduled_hc) - row.required_hc, 0.0)
        * intraday_service.interval_duration_hours(row.interval_start, row.interval_end)
        for row in intervals
    )
    overtime_h = overtime_service.compute_overtime_report(
        session,
        start_date=target_date,
        end_date=target_date,
        campaign_id=campaign_id,
        skill_id=skill_id,
    ).ot_required_hours

    workforce_plan = _latest_workforce_plan(session, campaign_id, target_date)
    metrics = calculate_metrics(workforce_plan) if workforce_plan else None
    roster = roster_snapshot(session, campaign_id=campaign_id, period=f"{target_date.year:04d}-{target_date.month:02d}")

    available_agents = [
        employee for employee in session.exec(
            select(Employee).where(
                Employee.campaign_id == campaign_id,
                Employee.status == EmployeeStatus.ACTIVE,
            ).order_by(Employee.last_name, Employee.first_name)
        ).all()
        if employee.id in {
            row.employee_id for row in session.exec(select(EmployeeSkill).where(EmployeeSkill.skill_id == skill_id)).all()
        }
        and not session.exec(
            select(EmployeeAbsence).where(
                EmployeeAbsence.employee_id == employee.id,
                EmployeeAbsence.start_date <= target_date,
                EmployeeAbsence.end_date >= target_date,
            )
        ).first()
    ]

    recommendations = planner_service.recommend_shift_mix(
        intervals,
        list(session.exec(select(__import__("app.models.shift", fromlist=["Shift"]).Shift).where(__import__("app.models.shift", fromlist=["Shift"]).Shift.is_active == True)).all()),  # noqa: E712
        max_agents=len(available_agents),
    )

    return ControlTowerData(
        target_date=target_date,
        campaign=campaign,
        skill=skill,
        ltf=ltf,
        intervals=controls,
        forecast_volume=forecast_volume,
        actual_volume=actual_volume,
        forecast_accuracy_pct=accuracy,
        peak_required_hc=peak_required,
        peak_scheduled_hc=peak_scheduled,
        peak_actual_hc=peak_actual,
        shortage_hc_hours=shortage_h,
        surplus_hc_hours=surplus_h,
        overtime_hours=overtime_h,
        workforce_plan=workforce_plan,
        workforce_metrics=metrics,
        roster_hc=roster.active_roster_hc,
        recommendations=recommendations,
        generated_at=target_date,
    )


def build_week_board(session: Session, *, week_start: date, campaign_id: int, skill_id: int):
    employees = list(
        session.exec(
            select(Employee)
            .where(Employee.campaign_id == campaign_id)
            .where(Employee.status == "active")
            .order_by(Employee.last_name, Employee.first_name)
        ).all()
    )
    rows = []
    for employee in employees:
        days = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            entry = session.exec(
                select(__import__("app.models.schedule", fromlist=["ScheduleEntry"]).ScheduleEntry).where(
                    __import__("app.models.schedule", fromlist=["ScheduleEntry"]).ScheduleEntry.employee_id == employee.id,
                    __import__("app.models.schedule", fromlist=["ScheduleEntry"]).ScheduleEntry.date == day,
                )
            ).first()
            shift = None
            if entry and entry.shift_id:
                shift = session.get(__import__("app.models.shift", fromlist=["Shift"]).Shift, entry.shift_id)
            absence = session.exec(
                select(EmployeeAbsence).where(
                    EmployeeAbsence.employee_id == employee.id,
                    EmployeeAbsence.start_date <= day,
                    EmployeeAbsence.end_date >= day,
                )
            ).first()
            days.append({"date": day, "entry": entry, "shift": shift, "absence": absence})
        rows.append({"employee": employee, "days": days})
    return rows
