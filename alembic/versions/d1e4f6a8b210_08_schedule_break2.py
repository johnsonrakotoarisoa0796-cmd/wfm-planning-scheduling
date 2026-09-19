"""08 automatic schedule generator supports a second paid/unpaid break slot."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d1e4f6a8b210"
down_revision: Union[str, None] = "c8f1e2d3a704"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schedule_entries", sa.Column("break2_start", sa.Time(), nullable=True))
    op.add_column("schedule_entries", sa.Column("break2_end", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("schedule_entries", "break2_end")
    op.drop_column("schedule_entries", "break2_start")
