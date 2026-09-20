"""18 version WFM calculation engine on forecasts."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d6e7f8901234"
down_revision: Union[str, None] = "c5d6e7f89012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("forecast_versions", sa.Column("calculation_engine_version", sa.String(), nullable=False, server_default="legacy-v1"))
    op.execute("UPDATE forecast_versions SET calculation_engine_version = 'legacy-v1'")


def downgrade() -> None:
    op.drop_column("forecast_versions", "calculation_engine_version")
