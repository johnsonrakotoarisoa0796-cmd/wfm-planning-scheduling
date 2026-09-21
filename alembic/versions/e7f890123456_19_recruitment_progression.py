"""19 add actual recruitment progression counters."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7f890123456"
down_revision: Union[str, None] = "d6e7f8901234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = [
        ("recruited_hc", 0),
        ("training_hc", 0),
        ("nesting_hc", 0),
        ("production_hc", 0),
        ("exited_hc", 0),
    ]
    for name, default in columns:
        op.add_column("recruitment_plans", sa.Column(name, sa.Integer(), nullable=False, server_default=str(default)))


def downgrade() -> None:
    for name in ("exited_hc", "production_hc", "nesting_hc", "training_hc", "recruited_hc"):
        op.drop_column("recruitment_plans", name)
