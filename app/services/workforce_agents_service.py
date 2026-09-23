"""Gestion du référentiel Workforce / Agents."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Iterable

import pandas as pd
from sqlmodel import Session, select

from app.models.campaign import Campaign
from app.models.employee import Employee, EmployeeSkill
from app.models.enums import EmployeeStatus
from app.models.skill import Skill
from app.schemas.workforce import WorkforceEmployeeInput


FICTIONAL_FIRST_NAMES = [
    "Amelia", "Ava", "Chloe", "Daniel", "Ethan", "Grace", "Hannah", "Jack",
    "Liam", "Maya", "Noah", "Olivia", "Sophie", "Thomas", "Zoe", "Lucas",
    "Mila", "Oscar", "Ella", "Henry",
]
FICTIONAL_LAST_NAMES = [
    "Bennett", "Carter", "Cooper", "Foster", "Harris", "Hughes", "Jackson",
    "King", "Lewis", "Mason", "Mitchell", "Morgan", "Parker", "Reed",
    "Roberts", "Smith", "Taylor", "Turner", "Walker", "Wilson",
]


@dataclass(frozen=True)
class ImportResult:
    imported: int
    updated: int
    skipped: int


def list_employees(
    session: Session,
    *,
    search: str | None = None,
    campaign_id: int | None = None,
    skill_id: int | None = None,
    status: EmployeeStatus | None = None,
    data_source: str | None = None,
) -> list[Employee]:
    query = select(Employee).order_by(Employee.last_name, Employee.first_name, Employee.employee_code)
    if search:
        needle = f"%{search.strip().lower()}%"
        query = query.where(
            Employee.employee_code.ilike(needle)
            | Employee.first_name.ilike(needle)
            | Employee.last_name.ilike(needle)
        )
    if campaign_id is not None:
        query = query.where(Employee.campaign_id == campaign_id)
    if status is not None:
        query = query.where(Employee.status == status)
    if data_source in {"real", "synthetic"}:
        query = query.where(Employee.data_source == data_source)

    employees = list(session.exec(query).all())
    if skill_id is not None:
        employee_ids = {
            link.employee_id
            for link in session.exec(
                select(EmployeeSkill).where(EmployeeSkill.skill_id == skill_id)
            ).all()
        }
        employees = [employee for employee in employees if employee.id in employee_ids]
    return employees


def _validate_scope(session: Session, *, campaign_id: int, skill_id: int) -> tuple[Campaign, Skill]:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None or not campaign.is_active:
        raise ValueError("La campagne sélectionnée est introuvable ou inactive.")
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise ValueError(f"Le skill sélectionné (ID {skill_id}) est introuvable.")

    # Tolérance aux anciens formulaires/caches : si l'ancien formulaire a envoyé
    # l'ID d'un skill homonyme d'une autre campagne, on récupère le skill actif
    # de la campagne choisie portant le même nom. Cela évite un 400 après un
    # déploiement tout en conservant la validation métier côté serveur.
    if skill.campaign_id != campaign_id or not skill.is_active:
        replacement = session.exec(
            select(Skill).where(
                Skill.campaign_id == campaign_id,
                Skill.name == skill.name,
                Skill.is_active == True,  # noqa: E712
            )
        ).first()
        if replacement is not None:
            skill = replacement
        elif not skill.is_active:
            raise ValueError(f"Le skill « {skill.name} » (ID {skill_id}) est inactif.")
        else:
            raise ValueError(
                f"Le skill « {skill.name} » (ID {skill_id}) appartient à une autre campagne "
                f"et aucun skill équivalent n'est configuré pour « {campaign.name} »."
            )
    return campaign, skill


def create_employee(
    session: Session,
    data: WorkforceEmployeeInput,
    *,
    replace_existing: bool = False,
    commit: bool = True,
) -> Employee:
    _, skill = _validate_scope(session, campaign_id=data.campaign_id, skill_id=data.skill_id)

    existing = session.exec(
        select(Employee).where(Employee.employee_code == data.employee_code)
    ).first()
    if existing is not None and not replace_existing:
        raise ValueError(f"L'employee code {data.employee_code} existe déjà.")

    employee = existing or Employee(employee_code=data.employee_code)
    employee.first_name = data.first_name
    employee.last_name = data.last_name
    employee.campaign_id = data.campaign_id
    employee.hire_date = data.hire_date
    employee.termination_date = data.termination_date
    employee.status = data.status
    employee.weekly_hours_contract = data.weekly_hours_contract
    employee.timezone_name = data.timezone_name
    employee.data_source = data.data_source
    session.add(employee)
    session.flush()

    link = session.exec(
        select(EmployeeSkill).where(
            EmployeeSkill.employee_id == employee.id,
            EmployeeSkill.skill_id == skill.id,
        )
    ).first()
    if link is None:
        session.add(EmployeeSkill(employee_id=employee.id, skill_id=skill.id, is_primary=True))
    else:
        link.is_primary = True
        session.add(link)
    if commit:
        session.commit()
        session.refresh(employee)
    return employee


def _synthetic_code_prefix(prefix: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "", prefix.upper()) or "SYN"
    return f"SYN-{normalized}-"


def _next_synthetic_code_number(session: Session, prefix: str) -> int:
    code_prefix = _synthetic_code_prefix(prefix)
    rows = session.exec(
        select(Employee.employee_code).where(
            Employee.employee_code.startswith(code_prefix)
        )
    ).all()

    max_number = 0
    pattern = re.compile(rf"^{re.escape(code_prefix)}(\\d+)$")
    for code in rows:
        match = pattern.match(code)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return max_number + 1


def generate_synthetic_employees(
    session: Session,
    *,
    campaign_id: int,
    skill_id: int,
    count: int,
    hire_date: date,
    weekly_hours_contract: float = 40.0,
    timezone_name: str = "UTC",
) -> list[Employee]:
    if count < 1 or count > 500:
        raise ValueError("La génération fictive doit être comprise entre 1 et 500 agents.")
    if weekly_hours_contract <= 0 or weekly_hours_contract > 168:
        raise ValueError("Les heures contractuelles doivent être comprises entre 0 et 168.")
    from app.services.workforce_service import validate_timezone_name
    validate_timezone_name(timezone_name)
    _, skill = _validate_scope(session, campaign_id=campaign_id, skill_id=skill_id)

    prefix = f"{campaign_id}{skill_id}"
    next_number = _next_synthetic_code_number(session, prefix)
    code_prefix = _synthetic_code_prefix(prefix)

    created: list[Employee] = []
    for index in range(count):
        first_name = FICTIONAL_FIRST_NAMES[index % len(FICTIONAL_FIRST_NAMES)]
        last_name = FICTIONAL_LAST_NAMES[(index // len(FICTIONAL_FIRST_NAMES)) % len(FICTIONAL_LAST_NAMES)]
        code = f"{code_prefix}{next_number + index:04d}"
        created.append(
            Employee(
                employee_code=code,
                first_name=first_name,
                last_name=last_name,
                campaign_id=campaign_id,
                hire_date=hire_date,
                status=EmployeeStatus.ACTIVE,
                weekly_hours_contract=weekly_hours_contract,
                timezone_name=timezone_name,
                data_source="synthetic",
            )
        )

    # Un seul flush pour obtenir les IDs, puis une seule opération de commit.
    # L'ancienne implémentation faisait une requête DB pour chaque code et un
    # flush par agent : pour 140 agents, cela provoquait des milliers d'allers-
    # retours PostgreSQL sur Render et donnait l'impression que la génération
    # était bloquée.
    session.add_all(created)
    session.flush()
    session.add_all(
        [
            EmployeeSkill(employee_id=employee.id, skill_id=skill.id, is_primary=True)
            for employee in created
        ]
    )
    session.commit()
    for employee in created:
        session.refresh(employee)
    return created


def _read_import_dataframe(filename: str, content: bytes) -> pd.DataFrame:
    from io import BytesIO

    lower = filename.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        frame = pd.read_excel(BytesIO(content))
    else:
        frame = pd.read_csv(BytesIO(content))
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def import_real_employees(
    session: Session,
    *,
    filename: str,
    content: bytes,
    update_existing: bool = True,
) -> ImportResult:
    frame = _read_import_dataframe(filename, content)
    required = {
        "employee_code", "first_name", "last_name",
        "campaign_code", "skill_name", "hire_date",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("Colonnes manquantes: " + ", ".join(sorted(missing)))

    imported = updated = skipped = 0
    seen_codes: set[str] = set()

    for row_number, raw in frame.iterrows():
        line = int(row_number) + 2
        code = str(raw["employee_code"]).strip()
        if not code:
            raise ValueError(f"Ligne {line}: employee_code est obligatoire.")
        if code in seen_codes:
            raise ValueError(f"Ligne {line}: doublon employee_code={code}.")
        seen_codes.add(code)

        campaign_code = str(raw["campaign_code"]).strip().upper()
        campaign = session.exec(
            select(Campaign).where(Campaign.code == campaign_code)
        ).first()
        if campaign is None or not campaign.is_active:
            raise ValueError(f"Ligne {line}: campagne inconnue ou inactive: {campaign_code}.")

        skill_name = str(raw["skill_name"]).strip()
        skill = session.exec(
            select(Skill).where(
                Skill.campaign_id == campaign.id,
                Skill.name == skill_name,
                Skill.is_active == True,  # noqa: E712
            )
        ).first()
        if skill is None:
            raise ValueError(f"Ligne {line}: skill inconnu pour {campaign_code}: {skill_name}.")

        termination = raw.get("termination_date")
        termination_date = (
            pd.to_datetime(termination).date()
            if pd.notna(termination) and str(termination).strip()
            else None
        )
        weekly = float(raw.get("weekly_hours_contract", 40) or 40)
        timezone_name = str(raw.get("timezone_name", "UTC") or "UTC").strip()
        status_raw = str(raw.get("status", EmployeeStatus.ACTIVE.value) or EmployeeStatus.ACTIVE.value).strip().lower()
        try:
            status = EmployeeStatus(status_raw)
        except ValueError as exc:
            raise ValueError(
                f"Ligne {line}: status doit être active, leave ou terminated."
            ) from exc

        payload = WorkforceEmployeeInput(
            employee_code=code,
            first_name=str(raw["first_name"]).strip(),
            last_name=str(raw["last_name"]).strip(),
            campaign_id=campaign.id,
            skill_id=skill.id,
            hire_date=pd.to_datetime(raw["hire_date"]).date(),
            termination_date=termination_date,
            weekly_hours_contract=weekly,
            timezone_name=timezone_name,
            status=status,
            data_source="real",
        )

        existing = session.exec(
            select(Employee).where(Employee.employee_code == payload.employee_code)
        ).first()
        if existing is not None and not update_existing:
            skipped += 1
            continue

        create_employee(
            session,
            payload,
            replace_existing=existing is not None,
            commit=False,
        )
        if existing is not None:
            updated += 1
        else:
            imported += 1

    session.commit()
    return ImportResult(imported=imported, updated=updated, skipped=skipped)


def employee_skill_rows(session: Session, employee_ids: Iterable[int]) -> dict[int, list[Skill]]:
    ids = list(employee_ids)
    if not ids:
        return {}
    links = list(session.exec(
        select(EmployeeSkill).where(EmployeeSkill.employee_id.in_(ids))
    ).all())
    skills = {
        skill.id: skill
        for skill in session.exec(select(Skill).where(Skill.id.in_({link.skill_id for link in links}))).all()
    }
    primary_by_employee = {
        link.employee_id: link.skill_id
        for link in links
        if link.is_primary
    }
    rows: dict[int, list[Skill]] = {employee_id: [] for employee_id in ids}
    for link in links:
        skill = skills.get(link.skill_id)
        if skill is not None:
            rows[link.employee_id].append(skill)
    for employee_id, values in rows.items():
        primary_id = primary_by_employee.get(employee_id)
        values.sort(key=lambda item: (item.id != primary_id, item.name))
    return rows


def set_employee_status(session: Session, employee: Employee, status: EmployeeStatus) -> Employee:
    employee.status = status
    if status == EmployeeStatus.TERMINATED and employee.termination_date is None:
        employee.termination_date = date.today()
    if status == EmployeeStatus.ACTIVE and employee.termination_date is not None:
        employee.termination_date = None
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee
