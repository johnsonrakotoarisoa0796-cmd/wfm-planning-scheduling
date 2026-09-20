"""12 add configurable WFM compliance policies."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d0e1f2a3b456"
down_revision: Union[str, None] = "c9d0e1f2a345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False, server_default="Standard WFM"),
        sa.Column("max_consecutive_work_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_daily_hours", sa.Float(), nullable=False, server_default="10"),
        sa.Column("max_weekly_hours", sa.Float(), nullable=False, server_default="48"),
        sa.Column("max_weekly_overtime_hours", sa.Float(), nullable=False, server_default="8"),
        sa.Column("min_rest_hours", sa.Float(), nullable=False, server_default="11"),
        sa.Column("weekly_coverage_target_pct", sa.Float(), nullable=False, server_default="95"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_compliance_policies_campaign_id", "compliance_policies", ["campaign_id"])
    op.create_index("ix_compliance_policies_skill_id", "compliance_policies", ["skill_id"])
    op.create_index("ix_compliance_policies_is_active", "compliance_policies", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_compliance_policies_is_active", table_name="compliance_policies")
    op.drop_index("ix_compliance_policies_skill_id", table_name="compliance_policies")
    op.drop_index("ix_compliance_policies_campaign_id", table_name="compliance_policies")
    op.drop_table("compliance_policies")
