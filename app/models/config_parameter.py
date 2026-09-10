"""Paramètres métier configurables (Settings), §38.

Complète app/core/config.py (valeurs par défaut au niveau global) en
permettant une surcharge par campagne ou par skill sans redéploiement.
"""

from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import ConfigScope


class ConfigParameter(SQLModel, table=True):
    __tablename__ = "config_parameters"

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, nullable=False)
    value: str = Field(nullable=False)
    scope: ConfigScope = Field(default=ConfigScope.GLOBAL, index=True, nullable=False)
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id")
    skill_id: Optional[int] = Field(default=None, foreign_key="skills.id")
