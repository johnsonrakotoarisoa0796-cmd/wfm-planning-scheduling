"""06 weekly WFM forecast parameters, client STF volumes and recruitment ramp."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b6e7c4d1a902"
down_revision: Union[str, None] = "a4d8e2f1b903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ltf_forecasts", sa.Column("iso_year", sa.Integer(), nullable=True))
    op.add_column("ltf_forecasts", sa.Column("iso_week", sa.Integer(), nullable=True))
    op.add_column("ltf_forecasts", sa.Column("week_start_date", sa.Date(), nullable=True))
    op.create_index(op.f("ix_ltf_forecasts_iso_year"), "ltf_forecasts", ["iso_year"], unique=False)
    op.create_index(op.f("ix_ltf_forecasts_iso_week"), "ltf_forecasts", ["iso_week"], unique=False)
    op.create_index(op.f("ix_ltf_forecasts_week_start_date"), "ltf_forecasts", ["week_start_date"], unique=False)

    for name, default in (
        ("volume", "0"),
        ("aht_seconds", "0"),
        ("occupancy_pct", "0"),
        ("service_level_target_pct", "0"),
        ("answer_time_target_seconds", "0"),
        ("shrinkage_pct", "0"),
    ):
        op.add_column(
            "client_stf_intervals",
            sa.Column(name, sa.Float(), nullable=False, server_default=default),
        )

    op.create_index(
        op.f("ix_client_stf_intervals_plan_date_start"),
        "client_stf_intervals",
        ["plan_id", "date", "interval_start"],
        unique=True,
    )

    op.create_table(
        "weekly_wfm_parameters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("week_start_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("aht_seconds", sa.Float(), nullable=False, server_default="300"),
        sa.Column("occupancy_pct", sa.Float(), nullable=False, server_default="85"),
        sa.Column("service_level_target_pct", sa.Float(), nullable=False, server_default="80"),
        sa.Column("answer_time_target_seconds", sa.Float(), nullable=False, server_default="20"),
        sa.Column("shrinkage_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "iso_year", "iso_week", "campaign_id", "skill_id",
            name="uq_weekly_wfm_parameters_period_scope",
        ),
    )
    op.create_index(op.f("ix_weekly_wfm_parameters_iso_year"), "weekly_wfm_parameters", ["iso_year"], unique=False)
    op.create_index(op.f("ix_weekly_wfm_parameters_iso_week"), "weekly_wfm_parameters", ["iso_week"], unique=False)
    op.create_index(op.f("ix_weekly_wfm_parameters_week_start_date"), "weekly_wfm_parameters", ["week_start_date"], unique=False)
    op.create_index(op.f("ix_weekly_wfm_parameters_campaign_id"), "weekly_wfm_parameters", ["campaign_id"], unique=False)
    op.create_index(op.f("ix_weekly_wfm_parameters_skill_id"), "weekly_wfm_parameters", ["skill_id"], unique=False)

    op.create_table(
        "recruitment_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cohort_name", sa.String(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("headcount", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("weekly_hours_contract", sa.Float(), nullable=False, server_default="40"),
        sa.Column("training_weeks", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("nesting_weeks", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recruitment_plans_campaign_id"), "recruitment_plans", ["campaign_id"], unique=False)
    op.create_index(op.f("ix_recruitment_plans_skill_id"), "recruitment_plans", ["skill_id"], unique=False)
    op.create_index(op.f("ix_recruitment_plans_start_date"), "recruitment_plans", ["start_date"], unique=False)
    op.create_index(op.f("ix_recruitment_plans_is_active"), "recruitment_plans", ["is_active"], unique=False)

    op.create_table(
        "recruitment_ramp_weeks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("week_start_date", sa.Date(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False, server_default="training"),
        sa.Column("aht_seconds", sa.Float(), nullable=False, server_default="300"),
        sa.Column("occupancy_pct", sa.Float(), nullable=False, server_default="85"),
        sa.Column("capacity_factor_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["recruitment_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "week_number", name="uq_recruitment_ramp_week"),
    )
    op.create_index(op.f("ix_recruitment_ramp_weeks_plan_id"), "recruitment_ramp_weeks", ["plan_id"], unique=False)
    op.create_index(op.f("ix_recruitment_ramp_weeks_week_start_date"), "recruitment_ramp_weeks", ["week_start_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_recruitment_ramp_weeks_week_start_date"), table_name="recruitment_ramp_weeks")
    op.drop_index(op.f("ix_recruitment_ramp_weeks_plan_id"), table_name="recruitment_ramp_weeks")
    op.drop_table("recruitment_ramp_weeks")
    op.drop_index(op.f("ix_recruitment_plans_is_active"), table_name="recruitment_plans")
    op.drop_index(op.f("ix_recruitment_plans_start_date"), table_name="recruitment_plans")
    op.drop_index(op.f("ix_recruitment_plans_skill_id"), table_name="recruitment_plans")
    op.drop_index(op.f("ix_recruitment_plans_campaign_id"), table_name="recruitment_plans")
    op.drop_table("recruitment_plans")
    op.drop_index(op.f("ix_weekly_wfm_parameters_skill_id"), table_name="weekly_wfm_parameters")
    op.drop_index(op.f("ix_weekly_wfm_parameters_campaign_id"), table_name="weekly_wfm_parameters")
    op.drop_index(op.f("ix_weekly_wfm_parameters_week_start_date"), table_name="weekly_wfm_parameters")
    op.drop_index(op.f("ix_weekly_wfm_parameters_iso_week"), table_name="weekly_wfm_parameters")
    op.drop_index(op.f("ix_weekly_wfm_parameters_iso_year"), table_name="weekly_wfm_parameters")
    op.drop_table("weekly_wfm_parameters")
    op.drop_index(op.f("ix_client_stf_intervals_plan_date_start"), table_name="client_stf_intervals")
    for name in ("shrinkage_pct", "answer_time_target_seconds", "service_level_target_pct", "occupancy_pct", "aht_seconds", "volume"):
        op.drop_column("client_stf_intervals", name)
    op.drop_index(op.f("ix_ltf_forecasts_week_start_date"), table_name="ltf_forecasts")
    op.drop_index(op.f("ix_ltf_forecasts_iso_week"), table_name="ltf_forecasts")
    op.drop_index(op.f("ix_ltf_forecasts_iso_year"), table_name="ltf_forecasts")
    op.drop_column("ltf_forecasts", "week_start_date")
    op.drop_column("ltf_forecasts", "iso_week")
    op.drop_column("ltf_forecasts", "iso_year")
