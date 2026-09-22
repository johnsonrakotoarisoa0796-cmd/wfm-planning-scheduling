"""Couche IA optionnelle du WFM Copilot."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.campaign import Campaign
from app.models.employee import Employee, EmployeeAbsence, EmployeeSkill
from app.models.enums import EmployeeStatus
from app.models.intraday import IntervalForecast
from app.models.recruitment import RecruitmentPlan
from app.models.schedule import ScheduleEntry
from app.models.skill import Skill


class AIError(RuntimeError):
    """Erreur de configuration ou d'appel du provider IA."""


def ai_enabled() -> bool:
    settings = get_settings()
    return bool(settings.ai_api_key.strip() and settings.ai_model.strip())


def ai_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": ai_enabled(),
        "provider": settings.ai_provider,
        "model": settings.ai_model or "non configuré",
    }


def _extract_content(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("Réponse IA invalide : contenu absent.") from exc
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        text = "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
        if text:
            return text
    raise AIError("Réponse IA invalide : format du contenu non reconnu.")


def ask_ai(*, system_prompt: str, user_prompt: str, max_tokens: int = 1600) -> str:
    settings = get_settings()
    if not ai_enabled():
        raise AIError(
            "IA non configurée. Définissez AI_API_KEY et AI_MODEL dans l'environnement."
        )

    endpoint = f"{settings.ai_api_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.ai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.15,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise AIError(
            f"Provider IA HTTP {exc.response.status_code}: {exc.response.text[:500]}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise AIError(f"Impossible de contacter le provider IA : {exc}") from exc

    return _extract_content(payload)


def build_wfm_snapshot(
    session: Session,
    *,
    target_date: date,
    campaign_id: int | None = None,
    skill_id: int | None = None,
    days: int = 7,
) -> dict[str, Any]:
    end_date = target_date + timedelta(days=max(0, days - 1))
    campaign = session.get(Campaign, campaign_id) if campaign_id else None
    skill = session.get(Skill, skill_id) if skill_id else None

    query = select(IntervalForecast).where(
        IntervalForecast.date >= target_date,
        IntervalForecast.date <= end_date,
    )
    if campaign_id is not None:
        query = query.where(IntervalForecast.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(IntervalForecast.skill_id == skill_id)
    intervals = list(session.exec(query).all())
    actualized = [row for row in intervals if row.actual_volume is not None]

    def avg(rows: list[Any], field: str) -> float | None:
        values = [float(getattr(row, field)) for row in rows if getattr(row, field) is not None]
        return round(sum(values) / len(values), 2) if values else None

    employee_query = select(Employee).where(Employee.status == EmployeeStatus.ACTIVE)
    if campaign_id is not None:
        employee_query = employee_query.where(Employee.campaign_id == campaign_id)
    employees = list(session.exec(employee_query).all())

    eligible_ids = None
    if skill_id is not None:
        eligible_ids = {
            int(row.employee_id)
            for row in session.exec(
                select(EmployeeSkill).where(EmployeeSkill.skill_id == skill_id)
            ).all()
        }

    schedule_query = select(ScheduleEntry).where(
        ScheduleEntry.date >= target_date,
        ScheduleEntry.date <= end_date,
    )
    if campaign_id is not None:
        schedule_query = schedule_query.where(ScheduleEntry.campaign_id == campaign_id)
    if skill_id is not None:
        schedule_query = schedule_query.where(ScheduleEntry.skill_id == skill_id)
    schedule_entries = list(session.exec(schedule_query).all())

    absences = list(
        session.exec(
            select(EmployeeAbsence).where(
                EmployeeAbsence.start_date <= end_date,
                EmployeeAbsence.end_date >= target_date,
            )
        ).all()
    )

    recruitment_query = select(RecruitmentPlan).where(RecruitmentPlan.is_active == True)  # noqa: E712
    if campaign_id is not None:
        recruitment_query = recruitment_query.where(RecruitmentPlan.campaign_id == campaign_id)
    if skill_id is not None:
        recruitment_query = recruitment_query.where(RecruitmentPlan.skill_id == skill_id)
    recruitment_plans = list(session.exec(recruitment_query).all())

    active_employees = [
        employee for employee in employees
        if eligible_ids is None or employee.id in eligible_ids
    ]

    forecast_volume = sum(float(row.forecast_volume or 0) for row in intervals)
    actual_volume = sum(float(row.actual_volume or 0) for row in actualized)
    required_hours = sum(float(row.required_hc or 0) * 0.5 for row in intervals)
    scheduled_hours = sum(float(row.scheduled_hc or 0) * 0.5 for row in intervals)
    actual_hours = sum(float(row.actual_hc or 0) * 0.5 for row in actualized)
    actual_gap_hours = sum(float(row.staffing_gap or 0) * 0.5 for row in actualized)

    return {
        "period": {"start": target_date.isoformat(), "end": end_date.isoformat()},
        "scope": {
            "campaign": campaign.name if campaign else "Toutes",
            "skill": skill.name if skill else "Tous",
            "channel": skill.channel.value if skill else None,
            "concurrency_factor": float(skill.concurrency_factor) if skill else None,
        },
        "forecast": {
            "intervals": len(intervals),
            "actualized_intervals": len(actualized),
            "forecast_volume": round(forecast_volume, 1),
            "actual_volume": round(actual_volume, 1),
            "volume_delta": round(actual_volume - forecast_volume, 1) if actualized else None,
            "actual_aht_seconds": avg(actualized, "actual_aht_seconds"),
            "service_level_pct": avg(actualized, "service_level_pct"),
            "asa_seconds": avg(actualized, "asa_seconds"),
            "occupancy_pct": avg(actualized, "occupancy_pct"),
            "abandon_rate_pct": avg(actualized, "abandon_rate_pct"),
        },
        "staffing": {
            "required_hc_hours": round(required_hours, 1),
            "scheduled_hc_hours": round(scheduled_hours, 1),
            "actual_hc_hours": round(actual_hours, 1),
            "scheduled_gap_hours": round(scheduled_hours - required_hours, 1),
            "actual_gap_hours": round(actual_gap_hours, 1),
        },
        "workforce": {
            "active_agents": len(active_employees),
            "schedule_entries": len(schedule_entries),
            "day_off_entries": sum(1 for row in schedule_entries if row.is_day_off),
            "absence_records": len(absences),
        },
        "recruitment": {
            "active_cohorts": len(recruitment_plans),
            "planned_hc": sum(plan.headcount for plan in recruitment_plans),
            "training_hc": sum(plan.training_hc for plan in recruitment_plans),
            "nesting_hc": sum(plan.nesting_hc for plan in recruitment_plans),
            "production_hc": sum(plan.production_hc for plan in recruitment_plans),
        },
    }


def build_ai_instruction(
    mode: str,
    user_request: str,
    snapshot: dict[str, Any],
) -> tuple[str, str]:
    labels = {
        "copilot": "WFM Copilot général",
        "report": "Reporting WFM",
        "planning": "Planning, forecast et capacity",
        "scheduling": "Scheduling et couverture",
    }
    system_prompt = f"""Tu es un expert senior Workforce Management.
Mode : {labels.get(mode, labels["copilot"])}.

Utilise uniquement les données fournies. N'invente aucun chiffre.
Sépare faits, diagnostics et recommandations.
Pour un report : Synthèse, KPI, Risques, Actions.
Pour le planning : analyse forecast, capacité, staffing et propose des scénarios.
Pour le scheduling : propose des ajustements de couverture, shifts, pauses et contraintes.
Ne prétends jamais avoir modifié la base. Toute modification réelle est faite par le moteur WFM et confirmée par l'utilisateur.
Réponds en français et utilise les unités contacts, HC, heures, secondes et %."""

    user_prompt = f"""Demande :
{user_request.strip() or "Analyse la situation actuelle et indique les principaux points à traiter."}

Snapshot WFM déterministe :
{snapshot}

Réponse exploitable pour un planificateur WFM."""
    return system_prompt, user_prompt


def _pct_delta(actual: float | None, forecast: float | None) -> float | None:
    if actual is None or forecast in (None, 0):
        return None
    return round((actual - forecast) / forecast * 100.0, 1)


def build_free_analysis(
    *,
    mode: str,
    user_request: str,
    snapshot: dict[str, Any],
) -> str:
    """Analyse WFM localement sans appel externe ni coût API."""
    forecast = snapshot["forecast"]
    staffing = snapshot["staffing"]
    workforce = snapshot["workforce"]
    recruitment = snapshot["recruitment"]

    volume_delta_pct = _pct_delta(
        forecast.get("actual_volume"),
        forecast.get("forecast_volume"),
    )
    service_level = forecast.get("service_level_pct")
    occupancy = forecast.get("occupancy_pct")
    scheduled_gap = staffing.get("scheduled_gap_hours") or 0.0
    actual_gap = staffing.get("actual_gap_hours") or 0.0

    priorities: list[str] = []
    risks: list[str] = []
    actions: list[str] = []

    if volume_delta_pct is not None:
        if volume_delta_pct >= 10:
            priorities.append(
                f"Volume actual supérieur au forecast de {volume_delta_pct:.1f}%."
            )
            risks.append("Risque de sous-capacité si l'écart volume persiste.")
        elif volume_delta_pct <= -10:
            priorities.append(
                f"Volume actual inférieur au forecast de {abs(volume_delta_pct):.1f}%."
            )
            risks.append("Capacité potentiellement surdimensionnée.")
        else:
            priorities.append(
                f"Volume actual proche du forecast ({volume_delta_pct:+.1f}%)."
            )

    if scheduled_gap < -1:
        priorities.append(
            f"Sous-planification de {abs(scheduled_gap):.1f} heures HC sur le périmètre."
        )
        risks.append("Créneaux sous-couverts à traiter avant publication.")
        actions.append("Revoir les shifts et la capacité sur les intervalles en déficit.")
    elif scheduled_gap > 1:
        priorities.append(
            f"Sur-planification de {scheduled_gap:.1f} heures HC."
        )
        risks.append("Risque de surstaffing et de coût inutile.")
        actions.append("Réaffecter une partie des heures vers les créneaux déficitaires.")
    else:
        priorities.append("Le volume d'heures planifiées est proche du besoin calculé.")

    if actual_gap > 1:
        risks.append(
            f"Écart staffing actual de {actual_gap:.1f} heures HC sur les intervalles actualisés."
        )
        actions.append("Examiner les absences, retards et écarts de présence sur les périodes concernées.")

    if service_level is not None:
        if service_level < 80:
            risks.append(f"Service Level moyen sous 80% ({service_level:.1f}%).")
            actions.append("Prioriser les créneaux à faible Service Level avant les arbitrages de confort.")
        else:
            priorities.append(f"Service Level moyen à {service_level:.1f}%.")

    if occupancy is not None:
        if occupancy > 90:
            risks.append(f"Occupancy moyenne élevée ({occupancy:.1f}%).")
            actions.append("Vérifier le risque de surcharge avant d'augmenter la production.")
        elif occupancy < 70:
            priorities.append(f"Occupancy moyenne basse ({occupancy:.1f}%).")

    if workforce["absence_records"]:
        risks.append(f"{workforce['absence_records']} enregistrement(s) d'absence sur la période.")
        actions.append("Contrôler l'impact des absences sur la couverture des créneaux critiques.")

    if recruitment["training_hc"] or recruitment["nesting_hc"]:
        actions.append(
            f"Intégrer les cohortes en formation/nesting ({recruitment['training_hc']} / "
            f"{recruitment['nesting_hc']} HC) dans la capacité réellement productive."
        )

    if not actions:
        actions.append("Aucun écart majeur détecté par les règles déterministes actuelles.")

    mode_label = {
        "copilot": "Copilot WFM gratuit",
        "report": "Report WFM gratuit",
        "planning": "Analyse Planning / Capacity gratuite",
        "scheduling": "Analyse Scheduling gratuite",
    }.get(mode, "Analyse WFM gratuite")

    request_line = user_request.strip()
    lines = [
        f"## {mode_label}",
        f"Période : {snapshot['period']['start']} → {snapshot['period']['end']}",
        f"Périmètre : {snapshot['scope']['campaign']} · {snapshot['scope']['skill']}",
        "",
        "### KPI calculés localement",
        f"- Forecast volume : {forecast['forecast_volume']:.1f}",
        f"- Actual volume : {forecast['actual_volume']:.1f}",
        f"- Écart volume : {forecast.get('volume_delta') if forecast.get('volume_delta') is not None else 'donnée non disponible'}",
        f"- Required : {staffing['required_hc_hours']:.1f} h",
        f"- Scheduled : {staffing['scheduled_hc_hours']:.1f} h",
        f"- Actual : {staffing['actual_hc_hours']:.1f} h",
        f"- Agents actifs : {workforce['active_agents']}",
        f"- Absences : {workforce['absence_records']}",
        "",
        "### Priorités",
    ]
    lines.extend(f"- {item}" for item in priorities[:5])
    lines.extend(["", "### Risques"])
    lines.extend(f"- {item}" for item in risks[:5] or ["- Aucun risque majeur détecté par les règles actuelles."])
    lines.extend(["", "### Actions proposées"])
    lines.extend(f"- {item}" for item in actions[:6])

    if request_line:
        lines.extend([
            "",
            "### Demande utilisateur",
            f"Votre demande : {request_line}",
            "Cette version gratuite répond à partir des KPI et règles WFM calculés localement ; "
            "la génération libre de texte reste réservée au mode IA avancée.",
        ])

    return "\n".join(lines)
