"""21 add actual answered-within-threshold metric."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a6b7c8d9e012"
down_revision: Union[str, None] = "f89012345678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "actual_performance_raw",
        sa.Column("answered_within_threshold", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("actual_performance_raw", "answered_within_threshold")
