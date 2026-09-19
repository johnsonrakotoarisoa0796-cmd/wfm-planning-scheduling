"""11 link users to employees and add agent self-service requests."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c9d0e1f2a345"
down_revision: Union[str, None] = "b7c8d9e0f112"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("employee_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_employee_id", "users", ["employee_id"], unique=False)
    op.create_foreign_key(
        "fk_users_employee_id_employees",
        "users",
        "employees",
        ["employee_id"],
        ["id"],
    )
    op.create_table(
        "agent_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("request_type", sa.String(), nullable=False, server_default="time_off"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("shift_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index("ix_agent_requests_employee_id", "agent_requests", ["employee_id"], unique=False)
    op.create_index("ix_agent_requests_start_date", "agent_requests", ["start_date"], unique=False)
    op.create_index("ix_agent_requests_end_date", "agent_requests", ["end_date"], unique=False)
    op.create_index("ix_agent_requests_status", "agent_requests", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_requests_status", table_name="agent_requests")
    op.drop_index("ix_agent_requests_end_date", table_name="agent_requests")
    op.drop_index("ix_agent_requests_start_date", table_name="agent_requests")
    op.drop_index("ix_agent_requests_employee_id", table_name="agent_requests")
    op.drop_table("agent_requests")
    op.drop_constraint("fk_users_employee_id_employees", "users", type_="foreignkey")
    op.drop_index("ix_users_employee_id", table_name="users")
    op.drop_column("users", "employee_id")
