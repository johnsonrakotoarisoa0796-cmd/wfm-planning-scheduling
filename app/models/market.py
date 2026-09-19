"""Marchés opérationnels : FR, UK, DE, IN, ES, JP, NL, etc."""
from typing import Optional

from sqlmodel import Field, SQLModel


class Market(SQLModel, table=True):
    __tablename__ = "markets"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True, nullable=False)
    name: str = Field(nullable=False)
    language_code: str = Field(default="en", nullable=False)
    timezone_name: str = Field(default="UTC", nullable=False)
    is_active: bool = Field(default=True, nullable=False)
