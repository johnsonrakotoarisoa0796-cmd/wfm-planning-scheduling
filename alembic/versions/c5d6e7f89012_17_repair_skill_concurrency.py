"""17 repair existing skill concurrency values after enum migration."""
from typing import Sequence, Union

from alembic import op

revision: str = "c5d6e7f89012"
down_revision: Union[str, None] = "b4c5d6e7f890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL/SQLAlchemy Enum peut stocker le nom du membre (CHAT/EMAIL)
    # plutôt que sa valeur Python (chat/email).
    op.execute("UPDATE skills SET concurrency_factor = 3.0 WHERE CAST(channel AS TEXT) IN ('EMAIL', 'email')")
    op.execute("UPDATE skills SET concurrency_factor = 2.0 WHERE CAST(channel AS TEXT) IN ('CHAT', 'chat')")
    op.execute("UPDATE skills SET concurrency_factor = 1.0 WHERE CAST(channel AS TEXT) IN ('VOICE', 'voice', 'BACKOFFICE', 'backoffice')")


def downgrade() -> None:
    pass
