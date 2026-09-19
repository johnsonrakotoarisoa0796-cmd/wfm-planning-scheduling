"""Demandes self-service des agents."""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utc_now


class AgentRequest(SQLModel, table=True):
    __tablename__ = "agent_requests"

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employees.id", index=True, nullable=False)
    request_type: str = Field(default="time_off", nullable=False)
    start_date: date = Field(index=True, nullable=False)
    end_date: date = Field(index=True, nullable=False)
    shift_id: Optional[int] = Field(default=None, foreign_key="shifts.id")
    notes: Optional[str] = Field(default=None)
    status: str = Field(default="pending", index=True, nullable=False)
    requested_at: datetime = Field(default_factory=utc_now, nullable=False)
    reviewed_at: Optional[datetime] = Field(default=None)
    reviewed_by: Optional[int] = Field(default=None, foreign_key="users.id")
