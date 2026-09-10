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
    # Base contractuelle en heures/semaine, ne doit jamais être codée en dur
    # ailleurs (voir Settings et core/config.py pour le défaut global).
    weekly_hours_contract: float = Field(default=40.0, nullable=False)


class EmployeeSkill(SQLModel, table=True):
    """Table de liaison many-to-many Employee <-> Skill."""

    __tablename__ = "employee_skills"

    employee_id: int = Field(foreign_key="employees.id", primary_key=True)
    skill_id: int = Field(foreign_key="skills.id", primary_key=True)
    is_primary: bool = Field(default=False, nullable=False)
