"""09 campaign workforce planning."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f4a7b9c2d315"
down_revision: Union[str, None] = "d1e4f6a8b210"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_workforce_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("current_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("available_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("long_leave_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("training_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("nesting_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("other_unavailable_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("attrition_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hiring_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("transfers_in_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("transfers_out_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("required_hc", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "period", name="uq_campaign_workforce_period"),
    )
    op.create_index(
        "ix_campaign_workforce_plans_campaign_id",
        "campaign_workforce_plans",
        ["campaign_id"],
        unique=False,
    )
    op.create_index(
        "ix_campaign_workforce_plans_period",
        "campaign_workforce_plans",
        ["period"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_workforce_plans_period", table_name="campaign_workforce_plans")
    op.drop_index("ix_campaign_workforce_plans_campaign_id", table_name="campaign_workforce_plans")
    op.drop_table("campaign_workforce_plans")
