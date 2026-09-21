"""20 add email OTP state for user authentication."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f89012345678"
down_revision: Union[str, None] = "e7f890123456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_otp_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("email_otp_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("email_otp_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("email_otp_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "email_otp_attempts")
    op.drop_column("users", "email_otp_requested_at")
    op.drop_column("users", "email_otp_expires_at")
    op.drop_column("users", "email_otp_hash")
