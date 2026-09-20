"""Skills (files d'attente) rattachés à une campagne."""

from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import Channel


class Skill(SQLModel, table=True):
    __tablename__ = "skills"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    market_id: Optional[int] = Field(default=None, foreign_key="markets.id", index=True)
    name: str = Field(nullable=False)
    channel: Channel = Field(default=Channel.VOICE, nullable=False)
    concurrency_factor: float = Field(default=1.0, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
