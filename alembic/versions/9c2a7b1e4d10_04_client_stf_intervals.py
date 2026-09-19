"""04 client STF intervalisé.

Le STF client est une source de staffing distincte du STF hebdomadaire
calculé dans l'application. Une version courante existe par semaine,
campagne et skill, puis contient les besoins par intervalle.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c2a7b1e4d10"
down_revision: Union[str, None] = "7f5c2f9f2b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "client_stf_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_start_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False, server_default="STF client"),
        sa.Column("source", sa.String(), nullable=False, server_default="client"),
        sa.Column("import_batch_id", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_client_stf_plans_week_start_date"), "client_stf_plans", ["week_start_date"], unique=False)
    op.create_index(op.f("ix_client_stf_plans_campaign_id"), "client_stf_plans", ["campaign_id"], unique=False)
    op.create_index(op.f("ix_client_stf_plans_skill_id"), "client_stf_plans", ["skill_id"], unique=False)
    op.create_index(op.f("ix_client_stf_plans_import_batch_id"), "client_stf_plans", ["import_batch_id"], unique=False)
    op.create_index(op.f("ix_client_stf_plans_is_current"), "client_stf_plans", ["is_current"], unique=False)

    op.create_table(
        "client_stf_intervals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("interval_start", sa.Time(), nullable=False),
        sa.Column("interval_end", sa.Time(), nullable=False),
        sa.Column("required_hc", sa.Float(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["plan_id"], ["client_stf_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_client_stf_intervals_plan_id"), "client_stf_intervals", ["plan_id"], unique=False)
    op.create_index(op.f("ix_client_stf_intervals_date"), "client_stf_intervals", ["date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_client_stf_intervals_date"), table_name="client_stf_intervals")
    op.drop_index(op.f("ix_client_stf_intervals_plan_id"), table_name="client_stf_intervals")
    op.drop_table("client_stf_intervals")
    op.drop_index(op.f("ix_client_stf_plans_is_current"), table_name="client_stf_plans")
    op.drop_index(op.f("ix_client_stf_plans_import_batch_id"), table_name="client_stf_plans")
    op.drop_index(op.f("ix_client_stf_plans_skill_id"), table_name="client_stf_plans")
    op.drop_index(op.f("ix_client_stf_plans_campaign_id"), table_name="client_stf_plans")
    op.drop_index(op.f("ix_client_stf_plans_week_start_date"), table_name="client_stf_plans")
    op.drop_table("client_stf_plans")
