"""Campagnes du centre de contacts."""

from typing import Optional

from sqlmodel import Field, SQLModel


class Campaign(SQLModel, table=True):
    __tablename__ = "campaigns"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, nullable=False)
    code: str = Field(unique=True, index=True, nullable=False)
    description: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True, nullable=False)
