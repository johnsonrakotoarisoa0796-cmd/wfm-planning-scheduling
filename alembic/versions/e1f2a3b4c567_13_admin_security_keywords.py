"""13 add two hashed security keywords for admin accounts."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1f2a3b4c567"
down_revision: Union[str, None] = "d0e1f2a3b456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("admin_keyword1_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("admin_keyword2_hash", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "admin_keyword2_hash")
    op.drop_column("users", "admin_keyword1_hash")
