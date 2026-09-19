"""Gabarits de shifts (horaires configurables)."""

from datetime import time
from typing import Optional

from sqlmodel import Field, SQLModel


class Shift(SQLModel, table=True):
    __tablename__ = "shifts"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    start_time: time = Field(nullable=False)
    end_time: time = Field(nullable=False)
    break_minutes: int = Field(default=15, nullable=False)
    break_count: int = Field(default=2, nullable=False)
    break_paid: bool = Field(default=True, nullable=False)
    lunch_minutes: int = Field(default=60, nullable=False)
    lunch_paid: bool = Field(default=False, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
