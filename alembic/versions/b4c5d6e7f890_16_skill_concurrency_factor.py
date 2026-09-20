"""16 add configurable skill concurrency factor."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b4c5d6e7f890"
down_revision: Union[str, None] = "a3b4c5d6e789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("concurrency_factor", sa.Float(), nullable=False, server_default="1"))
    op.execute("UPDATE skills SET concurrency_factor = CASE channel WHEN 'email' THEN 3.0 WHEN 'chat' THEN 2.0 ELSE 1.0 END")


def downgrade() -> None:
    op.drop_column("skills", "concurrency_factor")
