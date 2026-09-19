"""05 channels, concurrency and markets."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a4d8e2f1b903"
down_revision: Union[str, None] = "9c2a7b1e4d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("language_code", sa.String(), nullable=False, server_default="en"),
        sa.Column("timezone_name", sa.String(), nullable=False, server_default="UTC"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_markets_code"), "markets", ["code"], unique=True)

    op.add_column("skills", sa.Column("market_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_skills_market_id"), "skills", ["market_id"], unique=False)
    op.create_foreign_key(
        "fk_skills_market_id_markets",
        "skills",
        "markets",
        ["market_id"],
        ["id"],
    )

    op.add_column("daily_forecasts", sa.Column("channel", sa.String(), nullable=False, server_default="voice"))
    op.add_column("interval_forecasts", sa.Column("channel", sa.String(), nullable=False, server_default="voice"))


def downgrade() -> None:
    op.drop_column("interval_forecasts", "channel")
    op.drop_column("daily_forecasts", "channel")
    op.drop_constraint("fk_skills_market_id_markets", "skills", type_="foreignkey")
    op.drop_index(op.f("ix_skills_market_id"), table_name="skills")
    op.drop_column("skills", "market_id")
    op.drop_index(op.f("ix_markets_code"), table_name="markets")
    op.drop_table("markets")
