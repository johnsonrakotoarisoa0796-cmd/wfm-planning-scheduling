"""Service métier pour le module Capacity Planning (§31 du cahier des charges).

Contrairement au LTF/STF (versionnés, jamais écrasés — §9), un plan de
capacité est un suivi opérationnel de l'état RH courant pour une période :
l'enregistrer à nouveau met à jour le plan existant plutôt que d'empiler
des versions, même logique que la saisie d'actuals en Daily/Intraday
(commit 08). Le Required HC affiché est un instantané du LTF actif au
moment de l'enregistrement — le module ne modifie jamais le LTF lui-même,
qui reste la source de vérité du forecast.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models.capacity import CapacityPlan
from app.models.forecast import ForecastVersion, LTFForecast
from app.schemas.capacity import CapacityPlanInput
from app.services import kpi_service
from app.services.forecast_service import get_current_ltf_forecast


def resolve_required_hc(
    session: Session,
    *,
    period: str,
    campaign_id: int,
    skill_id: int,
) -> tuple[float | None, str | None, list[LTFForecast]]:
    """Résout le Required HC pour un mois.

    Priorité:
    1) LTF mensuel courant du mois;
    2) pic des LTF hebdomadaires courants qui chevauchent le mois.
    Les anciens LTF hebdomadaires dont week_start_date est NULL sont
    reconstruits depuis iso_year/iso_week.
    """
    year, month = (int(part) for part in period.split("-"))
    monthly = get_current_ltf_forecast(
        session,
        year=year,
        month=month,
        campaign_id=campaign_id,
        skill_id=skill_id,
    )
    if monthly is not None:
        return monthly.headcount_required, f"LTF mensuel #{monthly.id}", [monthly]

    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])

    candidates = list(
        session.exec(
            select(LTFForecast)
            .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
            .where(
                LTFForecast.campaign_id == campaign_id,
                LTFForecast.skill_id == skill_id,
                ForecastVersion.is_current == True,  # noqa: E712
                LTFForecast.iso_year.is_not(None),
                LTFForecast.iso_week.is_not(None),
            )
        ).all()
    )

    weekly: list[LTFForecast] = []
    for row in candidates:
        start = row.week_start_date
        if start is None and row.iso_year is not None and row.iso_week is not None:
            try:
                start = date.fromisocalendar(row.iso_year, row.iso_week, 1)
            except ValueError:
                continue
        if start is None:
            continue
        end = start + timedelta(days=6)
        if start <= month_end and end >= month_start:
            weekly.append(row)

    if not weekly:
        return None, None, []

    peak = max(row.headcount_required for row in weekly)
    weeks = [f"W{row.iso_week:02d}/{row.iso_year}" for row in sorted(
        weekly,
        key=lambda item: (item.iso_year or 0, item.iso_week or 0),
    )]
    return peak, f"Pic LTF hebdomadaire · {', '.join(weeks)}", weekly


def upsert_capacity_plan(session: Session, data: CapacityPlanInput, created_by_user_id: int) -> CapacityPlan:
    """Crée ou met à jour le plan de capacité d'une période/campagne/skill.

    Échoue si aucun LTF actif ne couvre cette période — le Required HC et
    le calcul de gap n'ont pas de sens sans plan de référence (même
    logique de dépendance que le STF vis-à-vis du LTF).
    """
    required_hc, required_source, _reference_ltfs = resolve_required_hc(
        session,
        period=data.period,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
    )
    if required_hc is None:
        raise ValueError(
            f"Aucun LTF actif couvrant {data.period} sur cette campagne/skill — "
            "créez un LTF mensuel ou au moins un LTF hebdomadaire couvrant le mois."
        )

    projected_hc = kpi_service.projected_headcount(
        current_hc=data.current_hc,
        hiring=data.hiring,
        transfers_in=data.transfers_in,
        transfers_out=data.transfers_out,
        attrition_pct=data.attrition_pct,
    )
    projected_available_hc = kpi_service.projected_available_headcount(
        projected_hc=projected_hc,
        absenteeism_pct=data.absenteeism_pct,
    )

    existing = session.exec(
        select(CapacityPlan).where(
            CapacityPlan.period == data.period,
            CapacityPlan.campaign_id == data.campaign_id,
            CapacityPlan.skill_id == data.skill_id,
        )
    ).first()

    plan = existing or CapacityPlan(period=data.period, campaign_id=data.campaign_id, skill_id=data.skill_id)

    plan.current_hc = data.current_hc
    plan.required_hc = required_hc
    plan.hiring = data.hiring
    plan.transfers_in = data.transfers_in
    plan.transfers_out = data.transfers_out
    plan.attrition_pct = data.attrition_pct
    plan.absenteeism_pct = data.absenteeism_pct
    plan.projected_hc = projected_hc
    plan.projected_available_hc = projected_available_hc
    plan.notes = data.notes
    plan.created_by = created_by_user_id

    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def list_capacity_plans(
    session: Session,
    *,
    period: Optional[str] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
) -> list[CapacityPlan]:
    query = select(CapacityPlan)
    if period is not None:
        query = query.where(CapacityPlan.period == period)
    if campaign_id is not None:
        query = query.where(CapacityPlan.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(CapacityPlan.skill_id == skill_id)
    query = query.order_by(CapacityPlan.period.desc())
    return list(session.exec(query).all())
