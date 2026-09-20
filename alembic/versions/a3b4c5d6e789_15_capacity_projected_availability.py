"""15 separate projected headcount from projected availability."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3b4c5d6e789"
down_revision: Union[str, None] = "f2a3b4c5d678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "capacity_plans",
        sa.Column("projected_available_hc", sa.Float(), nullable=False, server_default="0"),
    )
    op.execute(
        """
        UPDATE capacity_plans
        SET projected_available_hc =
            GREATEST(
                0,
                projected_hc * (1 - COALESCE(absenteeism_pct, 0) / 100.0)
            )
        """
    )


def downgrade() -> None:
    op.drop_column("capacity_plans", "projected_available_hc")
