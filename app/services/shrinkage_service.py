"""Service métier pour le module Shrinkage (§23-§25 du cahier des charges).

Indoor (Break, Meeting, Personal Time, Outage, Project, Training) et
Outdoor (Leave, Absenteeism) sont deux grandes catégories, chacune composée
de plusieurs ShrinkageCategory — l'administrateur peut en ajouter/modifier
plus tard (§23). Les catégories par défaut sont créées au démarrage de
l'application (voir app/main.py:bootstrap_shrinkage_categories), pas ici.

Une seule vue de rapport sert les trois granularités du §25 (Monthly/
Weekly/Daily Shrinkage) : l'utilisateur choisit une plage de dates, et un
mois/une semaine/un jour ne sont que des plages particulières — inutile de
tripler le code pour trois pages qui feraient exactement le même calcul.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.employee import Employee, EmployeeAbsence, EmployeeSkill
from app.models.enums import EmployeeStatus, ShrinkageType
from app.models.shrinkage import ShrinkageCategory, ShrinkageRecord
from app.schemas.shrinkage import ShrinkageRecordInput
from app.services import kpi_service, workforce_service
from app.services.forecast_service import count_weekdays_in_range

settings = get_settings()


def record_shrinkage(session: Session, data: ShrinkageRecordInput) -> ShrinkageRecord:
    """Enregistre une occurrence de shrinkage (§23)."""
    record = ShrinkageRecord(
        employee_id=data.employee_id,
        category_id=data.category_id,
        date=data.record_date,
        hours=data.hours,
        campaign_id=data.campaign_id,
        skill_id=data.skill_id,
        notes=data.notes,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def list_shrinkage_records(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    campaign_id: Optional[int] = None,
    skill_id: Optional[int] = None,
) -> list[ShrinkageRecord]:
    query = select(ShrinkageRecord).where(ShrinkageRecord.date >= start_date, ShrinkageRecord.date <= end_date)
    if campaign_id is not None:
        query = query.where(ShrinkageRecord.campaign_id == campaign_id)
    if skill_id is not None:
        query = query.where(ShrinkageRecord.skill_id == skill_id)
    return list(session.exec(query.order_by(ShrinkageRecord.date)).all())


def list_active_categories(session: Session) -> list[ShrinkageCategory]:
    return list(session.exec(select(ShrinkageCategory).where(ShrinkageCategory.is_active == True)).all())  # noqa: E712


def _count_active_employees_for_skill(session: Session, *, skill_id: int) -> int:
    """Effectif actif rattaché à ce skill (via EmployeeSkill) — base du
    calcul de Paid Hours pour le rapport (§19), pas le HC théorique d'un
    forecast."""
    query = (
        select(Employee)
        .join(EmployeeSkill, EmployeeSkill.employee_id == Employee.id)
        .where(EmployeeSkill.skill_id == skill_id, Employee.status == EmployeeStatus.ACTIVE)
    )
    return len(session.exec(query).all())


@dataclass(frozen=True)
class ShrinkageSummary:
    """Résumé shrinkage pour une période/campagne/skill (§24-§25)."""

    paid_hours: float
    indoor_hours: float
    outdoor_hours: float
    total_hours: float
    total_pct: float
    available_hours: float
    paid_absence_hours: float = 0.0
    unpaid_absence_hours: float = 0.0
    by_category_hours: dict = field(default_factory=dict)  # code -> heures
    by_category_pct: dict = field(default_factory=dict)  # code -> % des Paid Hours


def compute_shrinkage_summary(
    session: Session,
    records: list[ShrinkageRecord],
    categories: list[ShrinkageCategory],
    *,
    skill_id: int,
    start_date: date,
    end_date: date,
) -> ShrinkageSummary:
    """Calcule le résumé shrinkage (§24) pour un ensemble d'enregistrements.

    Paid Hours = effectif actif du skill x heures/jour x jours ouvrés de la
    période (§19) — la référence pour le %, pas les heures payées
    théoriques d'un forecast LTF/STF (qui reflètent un HC requis, pas
    l'effectif réel suivi ici).
    """
    categories_by_id = {c.id: c for c in categories}

    indoor_hours = sum(
        r.hours for r in records
        if categories_by_id.get(r.category_id) and categories_by_id[r.category_id].type == ShrinkageType.INDOOR
    )
    outdoor_hours = sum(
        r.hours for r in records
        if categories_by_id.get(r.category_id) and categories_by_id[r.category_id].type == ShrinkageType.OUTDOOR
    )
    total_hours = indoor_hours + outdoor_hours

    employees = list(
        session.exec(
            select(Employee)
            .join(EmployeeSkill, EmployeeSkill.employee_id == Employee.id)
            .where(
                EmployeeSkill.skill_id == skill_id,
                Employee.status == EmployeeStatus.ACTIVE,
            )
        ).all()
    )
    absences = list(
        session.exec(
            select(EmployeeAbsence).where(
                EmployeeAbsence.end_date >= start_date,
                EmployeeAbsence.start_date <= end_date,
            )
        ).all()
    )
    absences_by_employee: dict[int, list[EmployeeAbsence]] = {}
    for absence in absences:
        absences_by_employee.setdefault(absence.employee_id, []).append(absence)

    paid_hours_value = 0.0
    paid_absence_hours = 0.0
    unpaid_absence_hours = 0.0
    for employee in employees:
        paid, paid_abs, unpaid_abs = workforce_service.workforce_period_hours(
            employee,
            absences_by_employee.get(employee.id, []),
            start_date=start_date,
            end_date=end_date,
        )
        paid_hours_value += paid
        paid_absence_hours += paid_abs
        unpaid_absence_hours += unpaid_abs

    # Les absences payées sont du shrinkage : elles consomment des heures
    # payées mais ne fournissent aucune capacité opérationnelle.
    total_hours += paid_absence_hours
    total_pct = kpi_service.shrinkage_pct(total_hours, paid_hours_value)
    available_hours = paid_hours_value - total_hours

    by_category_hours: dict = {}
    for r in records:
        cat = categories_by_id.get(r.category_id)
        if cat is not None:
            by_category_hours[cat.code] = by_category_hours.get(cat.code, 0.0) + r.hours
    by_category_pct = {
        code: kpi_service.shrinkage_pct(hours, paid_hours_value) for code, hours in by_category_hours.items()
    }

    return ShrinkageSummary(
        paid_hours=paid_hours_value,
        indoor_hours=indoor_hours,
        outdoor_hours=outdoor_hours,
        total_hours=total_hours,
        total_pct=total_pct,
        available_hours=available_hours,
        by_category_hours=by_category_hours,
        by_category_pct=by_category_pct,
        paid_absence_hours=paid_absence_hours,
        unpaid_absence_hours=unpaid_absence_hours,
    )
