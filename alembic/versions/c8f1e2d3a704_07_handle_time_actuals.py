"""07 handle time components on interval forecasts."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c8f1e2d3a704"
down_revision: Union[str, None] = "b6e7c4d1a902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    for name in ("actual_talk_time_seconds", "actual_hold_time_seconds", "actual_acw_seconds"):
        op.add_column("interval_forecasts", sa.Column(name, sa.Float(), nullable=True))

def downgrade() -> None:
    for name in ("actual_acw_seconds", "actual_hold_time_seconds", "actual_talk_time_seconds"):
        op.drop_column("interval_forecasts", name)
