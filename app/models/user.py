"""Utilisateurs de l'application (authentification, RBAC)."""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utc_now
from app.models.enums import UserRole


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, nullable=False)
    hashed_password: str = Field(nullable=False)
    role: UserRole = Field(default=UserRole.VIEWER, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    # totp_secret est rempli lors de l'activation du 2FA (commit 03).
    totp_secret: Optional[str] = Field(default=None)
    employee_id: Optional[int] = Field(default=None, foreign_key="employees.id", index=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
