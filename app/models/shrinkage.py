"""Shrinkage indoor/outdoor (§23-§25), catégories extensibles par l'admin."""

from datetime import date as DateType
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import ShrinkageType


class ShrinkageCategory(SQLModel, table=True):
    __tablename__ = "shrinkage_categories"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    type: ShrinkageType = Field(nullable=False, index=True)
    code: str = Field(unique=True, index=True, nullable=False)
    is_active: bool = Field(default=True, nullable=False)


class ShrinkageRecord(SQLModel, table=True):
    __tablename__ = "shrinkage_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employees.id", index=True, nullable=False)
    category_id: int = Field(foreign_key="shrinkage_categories.id", index=True, nullable=False)
    date: DateType = Field(index=True, nullable=False)
    hours: float = Field(nullable=False)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    skill_id: int = Field(foreign_key="skills.id", index=True, nullable=False)
    notes: Optional[str] = Field(default=None)
