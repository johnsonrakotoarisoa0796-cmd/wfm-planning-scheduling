"""Service métier pour le forecast LTF Monthly (§6-§9 du cahier des charges).

Toute la logique de versioning (jamais d'écrasement — une seule version
"courante" par période/campagne/skill) et l'orchestration des moteurs KPI/
Erlang vit ici. Les routers n'appellent que ces fonctions, jamais de calcul
inline (règle §11 / §40).
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.enums import ForecastVersionType
from app.models.forecast import ForecastVersion, LTFForecast
from app.schemas.ltf import LTFCreateInput
from app.services import kpi_service
from app.services.erlang_service import apply_shrinkage

settings = get_settings()

MONTH_NAMES_FR = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def working_days_in_month(year: int, month: int) -> int:
    """Nombre de jours ouvrés (lundi-vendredi) dans le mois donné.

    Hypothèse V1 : semaine de travail lundi-vendredi, cohérent avec le
    défaut `working_days=5` de app/core/config.py. Une semaine de travail
    avec un jour de repos différent du week-end classique nécessiterait un
    calcul spécifique — hors périmètre V1.
    """
    _, days_in_month = calendar.monthrange(year, month)
    return sum(1 for day in range(1, days_in_month + 1) if date(year, month, day).weekday() < 5)


def _mark_previous_version_as_not_current(session: Session, data: LTFCreateInput) -> None:
    """Marque l'éventuelle version LTF courante existante comme non-courante.

    Ne supprime ni ne modifie jamais les valeurs déjà enregistrées — c'est
    la règle de non-écrasement du forecast (§9). L'historique complet reste
    consultable via ForecastVersion.is_current == False.
    """
    current_versions = session.exec(
        select(ForecastVersion).where(
            ForecastVersion.version_type == ForecastVersionType.LTF,
            ForecastVersion.campaign_id == data.campaign_id,
            ForecastVersion.skill_id == data.skill_id,
            ForecastVersion.is_current == True,  # noqa: E712
        )
    ).all()
    for version in current_versions:
        ltf_row = session.exec(
            select(LTFForecast).where(LTFForecast.forecast_version_id == version.id)
        ).first()
        if ltf_row is not None and ltf_row.year == data.year and ltf_row.month == data.month:
            version.is_current = False
            session.add(version)


def create_ltf_forecast(session: Session, data: LTFCreateInput, created_by_user_id: int) -> LTFForecast:
    """Crée une nouvelle version LTF à partir des entrées validées.

    Pipeline de calcul (chaque étape appelle le moteur KPI/Erlang, jamais de
    formule inline ici) :
      1. Workload Hours = Volume x AHT
      2. Net Required HC = Workload / (Heures dispo par agent x Occupancy)
         — formule agrégée mensuelle, PAS Erlang C (voir
         kpi_service.required_hc_aggregate pour la justification ; Erlang C
         s'applique au niveau Daily/Intraday, commit 08)
      3. Gross Required HC = Net Required HC / (1 - Shrinkage%)
      4. Paid Hours = Gross Required HC x heures/jour x jours ouvrés du mois
      5. Productive Hours = Paid Hours - Shrinkage Hours
      6. Production Hours = Productive Hours - Waiting Hours

    staffing_gap et overtime_required_hours restent à 0.0 à la création :
    ils seront calculés par les modules dédiés Capacity Planning (commit 09)
    et Overtime (commit 11), qui ont besoin de l'effectif réel/planifié —
    inconnu au moment de la simple saisie d'un forecast (§26, §31).
    """
    _mark_previous_version_as_not_current(session, data)

    total_shrinkage_pct = data.indoor_shrinkage_pct + data.outdoor_shrinkage_pct
    working_days = working_days_in_month(data.year, data.month)

    workload = kpi_service.workload_hours(data.forecast_volume, data.forecast_aht_seconds)
    available_hours_per_agent = kpi_service.paid_hours(1, settings.daily_hours, working_days)
    net_required_hc = kpi_service.required_hc_aggregate(workload, available_hours_per_agent, data.occupancy_required_pct)
    gross_required_hc = apply_shrinkage(net_required_hc, total_shrinkage_pct)

    paid_hours_value = kpi_service.paid_hours(gross_required_hc, settings.daily_hours, working_days)
    total_shrinkage_hours = paid_hours_value * (total_shrinkage_pct / 100)
    productive_hours_value = kpi_service.productive_hours(paid_hours_value, total_shrinkage_hours)
    waiting_hours = max(productive_hours_value - workload, 0.0)
    production_hours_value = kpi_service.production_hours(productive_hours_value, waiting_hours)

    period_start = date(data.year, data.month, 1)
    _, last_day = calendar.monthrange(data.year, data.month)
    period_end = date(data.year, data.month, last_day)

    version = ForecastVersion(
        version_type=ForecastVersionType.LTF,
        period_start=period_start,
        period_end=period_end,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
        label=f"LTF {MONTH_NAMES_FR[data.month]} {data.year}",
        created_by=created_by_user_id,
        notes=data.notes,
        is_current=True,
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    ltf = LTFForecast(
        forecast_version_id=version.id,
        year=data.year,
        month=data.month,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
        forecast_volume=data.forecast_volume,
        forecast_aht_seconds=data.forecast_aht_seconds,
        aht_required_seconds=data.aht_required_seconds,
        occupancy_required_pct=data.occupancy_required_pct,
        service_level_target_pct=data.service_level_target_pct,
        asa_target_seconds=data.asa_target_seconds,
        headcount_required=gross_required_hc,
        paid_hours=paid_hours_value,
        productive_hours=productive_hours_value,
        production_hours=production_hours_value,
        waiting_hours=waiting_hours,
        indoor_shrinkage_pct=data.indoor_shrinkage_pct,
        outdoor_shrinkage_pct=data.outdoor_shrinkage_pct,
        total_shrinkage_pct=total_shrinkage_pct,
        available_hours=productive_hours_value,
        staffing_gap=0.0,
        overtime_required_hours=0.0,
    )
    session.add(ltf)
    session.commit()
    session.refresh(ltf)
    return ltf


def list_current_ltf_forecasts(
    session: Session,
    *,
    year: Optional[int] = None,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
) -> list[LTFForecast]:
    """Liste les forecasts LTF courants (is_current=True sur leur version),
    avec filtres optionnels (§43)."""
    query = (
        select(LTFForecast)
        .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
        .where(ForecastVersion.is_current == True)  # noqa: E712
    )
    if year is not None:
        query = query.where(LTFForecast.year == year)
    if campaign_id is not None:
        query = query.where(LTFForecast.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(LTFForecast.skill_id == skill_id)
    query = query.order_by(LTFForecast.year, LTFForecast.month)
    return list(session.exec(query).all())


def get_ltf_version_history(
    session: Session, *, campaign_id: int, skill_id: int, year: int, month: int
) -> list[LTFForecast]:
    """Historique complet (toutes versions, courante ou non) d'un couple
    campagne/skill/mois donné, du plus ancien au plus récent — utile pour
    comparer l'évolution d'un forecast (§9)."""
    query = (
        select(LTFForecast)
        .join(ForecastVersion, LTFForecast.forecast_version_id == ForecastVersion.id)
        .where(
            LTFForecast.campaign_id == campaign_id,
            LTFForecast.skill_id == skill_id,
            LTFForecast.year == year,
            LTFForecast.month == month,
        )
        .order_by(ForecastVersion.created_at)
    )
    return list(session.exec(query).all())
