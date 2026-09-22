"""Employés et leur affectation aux skills (M2M)."""

from datetime import date
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import EmployeeStatus


class Employee(SQLModel, table=True):
    __tablename__ = "employees"

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_code: str = Field(unique=True, index=True, nullable=False)
    first_name: str = Field(nullable=False)
    last_name: str = Field(nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    hire_date: date = Field(nullable=False)
    termination_date: Optional[date] = Field(default=None)
    status: EmployeeStatus = Field(default=EmployeeStatus.ACTIVE, nullable=False)
    # real = données RH/OPS réelles ; synthetic = données fictives générées par WFM
    data_source: str = Field(default="real", nullable=False, index=True)
    # Base contractuelle en heures/semaine, ne doit jamais être codée en dur
    # ailleurs (voir Settings et core/config.py pour le défaut global).
    weekly_hours_contract: float = Field(default=40.0, nullable=False)
    timezone_name: str = Field(default="UTC", nullable=False)


class EmployeeSkill(SQLModel, table=True):
    """Table de liaison many-to-many Employee <-> Skill."""

    __tablename__ = "employee_skills"

    employee_id: int = Field(foreign_key="employees.id", primary_key=True)
    skill_id: int = Field(foreign_key="skills.id", primary_key=True)
    is_primary: bool = Field(default=False, nullable=False)


class EmployeeAbsence(SQLModel, table=True):
    """Absence datée d'un agent : maternité, disponibilité ou congé.

    paid distingue le statut contractuel de la disponibilité opérationnelle:
    un congé payé reste rémunéré mais l'agent reste indisponible au staffing;
    un congé non payé ne génère ni paid hours ni capacité opérationnelle.
    """

    __tablename__ = "employee_absences"

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employees.id", index=True, nullable=False)
    start_date: date = Field(index=True, nullable=False)
    end_date: date = Field(index=True, nullable=False)
    absence_type: str = Field(nullable=False)
    paid: bool = Field(default=False, nullable=False)
    notes: Optional[str] = Field(default=None)
