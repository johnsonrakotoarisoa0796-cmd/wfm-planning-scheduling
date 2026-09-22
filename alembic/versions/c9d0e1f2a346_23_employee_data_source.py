"""23 add employee data source to distinguish real vs synthetic workforce data."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c9d0e1f2a346"
down_revision: Union[str, None] = "b7c8d9e0f113"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("data_source", sa.String(length=20), nullable=False, server_default="real"),
    )
    op.alter_column("employees", "data_source", server_default=None)


def downgrade() -> None:
    op.drop_column("employees", "data_source")
