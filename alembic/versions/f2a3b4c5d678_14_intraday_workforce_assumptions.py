"""14 add intraday workforce assumptions."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2a3b4c5d678"
down_revision: Union[str, None] = "e1f2a3b4c567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interval_forecasts", sa.Column("handling_time_seconds", sa.Float(), nullable=False, server_default="0"))
    op.add_column("interval_forecasts", sa.Column("absence_rate_pct", sa.Float(), nullable=False, server_default="0"))
    op.add_column("interval_forecasts", sa.Column("leave_rate_pct", sa.Float(), nullable=False, server_default="0"))
    op.add_column("interval_forecasts", sa.Column("absence_hours", sa.Float(), nullable=False, server_default="0"))
    op.add_column("interval_forecasts", sa.Column("leave_hours", sa.Float(), nullable=False, server_default="0"))
    op.add_column("interval_forecasts", sa.Column("break_15m_pct", sa.Float(), nullable=False, server_default="0"))
    op.add_column("interval_forecasts", sa.Column("lunch_break_pct", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("interval_forecasts", "lunch_break_pct")
    op.drop_column("interval_forecasts", "break_15m_pct")
    op.drop_column("interval_forecasts", "leave_hours")
    op.drop_column("interval_forecasts", "absence_hours")
    op.drop_column("interval_forecasts", "leave_rate_pct")
    op.drop_column("interval_forecasts", "absence_rate_pct")
    op.drop_column("interval_forecasts", "handling_time_seconds")
