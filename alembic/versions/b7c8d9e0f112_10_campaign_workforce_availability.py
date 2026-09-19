"""10 enrich campaign workforce availability."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7c8d9e0f112"
down_revision: Union[str, None] = "f4a7b9c2d315"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaign_workforce_plans",
        sa.Column("planned_leave_hc", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "campaign_workforce_plans",
        sa.Column("unplanned_absence_hc", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("campaign_workforce_plans", "unplanned_absence_hc")
    op.drop_column("campaign_workforce_plans", "planned_leave_hc")
