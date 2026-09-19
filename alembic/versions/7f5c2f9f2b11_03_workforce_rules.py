"""03 workforce rules: breaks, employee timezone and absences

Revision ID: 7f5c2f9f2b11
Revises: c35734c4834f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f5c2f9f2b11"
down_revision: Union[str, None] = "c35734c4834f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("timezone_name", sa.String(), nullable=False, server_default="UTC"))

    op.add_column("shifts", sa.Column("break_count", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("shifts", sa.Column("break_paid", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("shifts", sa.Column("lunch_paid", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "employee_absences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("absence_type", sa.String(), nullable=False),
        sa.Column("paid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_employee_absences_employee_id"), "employee_absences", ["employee_id"], unique=False)
    op.create_index(op.f("ix_employee_absences_start_date"), "employee_absences", ["start_date"], unique=False)
    op.create_index(op.f("ix_employee_absences_end_date"), "employee_absences", ["end_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_employee_absences_end_date"), table_name="employee_absences")
    op.drop_index(op.f("ix_employee_absences_start_date"), table_name="employee_absences")
    op.drop_index(op.f("ix_employee_absences_employee_id"), table_name="employee_absences")
    op.drop_table("employee_absences")
    op.drop_column("shifts", "lunch_paid")
    op.drop_column("shifts", "break_paid")
    op.drop_column("shifts", "break_count")
    op.drop_column("employees", "timezone_name")
