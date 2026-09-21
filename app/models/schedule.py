"""Affectation planning d'un employé pour une date donnée.

Les colonnes break_start/break_end/lunch_start/lunch_end permettent au
scheduling_service de calculer le HC disponible avant/après pause sur un
intervalle donné (règle §34 du cahier des charges).
"""

from datetime import date as DateType
from datetime import time
from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint


class ScheduleEntry(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_schedule_employee_date"),
    )

    __tablename__ = "schedule_entries"

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employees.id", index=True, nullable=False)
    shift_id: Optional[int] = Field(default=None, foreign_key="shifts.id")
    date: DateType = Field(index=True, nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    is_day_off: bool = Field(default=False, nullable=False)
    break_start: Optional[time] = Field(default=None)
    break_end: Optional[time] = Field(default=None)
    break2_start: Optional[time] = Field(default=None)
    break2_end: Optional[time] = Field(default=None)
    lunch_start: Optional[time] = Field(default=None)
    lunch_end: Optional[time] = Field(default=None)
