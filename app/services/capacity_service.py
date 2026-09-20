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


def upsert_capacity_plan(session: Session, data: CapacityPlanInput, created_by_user_id: int) -> CapacityPlan:
    """Crée ou met à jour le plan de capacité d'une période/campagne/skill.

    Échoue si aucun LTF actif ne couvre cette période — le Required HC et
    le calcul de gap n'ont pas de sens sans plan de référence (même
    logique de dépendance que le STF vis-à-vis du LTF).
    """
    year, month = (int(part) for part in data.period.split("-"))
    ltf = get_current_ltf_forecast(
        session,
        year=year,
        month=month,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
    )

    required_hc = None
    required_source = None
    if ltf is not None:
        required_hc = ltf.headcount_required
        required_source = f"LTF mensuel #{ltf.id}"
    else:
        month_start = date(year, month, 1)
        month_end = date(year, month, monthrange(year, month)[1])
        weekly_ltfs = list(
            session.exec(
                select(LTFForecast)
                .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
                .where(
                    LTFForecast.campaign_id == data.campaign_id,
                    LTFForecast.skill_id == data.skill_id,
                    LTFForecast.iso_year.is_not(None),
                    LTFForecast.iso_week.is_not(None),
                    LTFForecast.week_start_date <= month_end,
                    (LTFForecast.week_start_date + timedelta(days=6)) >= month_start,
                    ForecastVersion.is_current == True,  # noqa: E712
                )
            ).all()
        )
        if weekly_ltfs:
            required_hc = max(row.headcount_required for row in weekly_ltfs)
            required_source = f"Peak weekly LTF ({len(weekly_ltfs)} semaine(s))"

    if required_hc is None:
        raise ValueError(
            f"Aucun LTF actif couvrant {data.period} sur cette campagne/skill — "
            "créez un LTF mensuel ou des LTF hebdomadaires pour cette période."
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
