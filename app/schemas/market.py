"""Schémas de gestion des marchés."""
from pydantic import BaseModel, Field


class MarketInput(BaseModel):
    code: str = Field(min_length=2, max_length=10)
    name: str = Field(min_length=1, max_length=100)
    language_code: str = Field(min_length=2, max_length=10)
    timezone_name: str = Field(min_length=1, max_length=100)
