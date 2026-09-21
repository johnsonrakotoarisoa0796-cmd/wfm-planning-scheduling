"""22 add database uniqueness constraints for WFM scope keys."""
from typing import Sequence, Union

from alembic import op

revision: str = "b7c8d9e0f113"
down_revision: Union[str, None] = "a6b7c8d9e012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_schedule_employee_date",
        "schedule_entries",
        ["employee_id", "date"],
    )
    op.create_unique_constraint(
        "uq_capacity_campaign_skill_period",
        "capacity_plans",
        ["campaign_id", "skill_id", "period"],
    )
    op.create_unique_constraint(
        "uq_overtime_campaign_skill_period",
        "overtime_plans",
        ["campaign_id", "skill_id", "period_type", "period_key"],
    )
    op.create_unique_constraint(
        "uq_interval_forecast_scope",
        "interval_forecasts",
        ["date", "interval_start", "campaign_id", "skill_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_interval_forecast_scope", "interval_forecasts", type_="unique")
    op.drop_constraint("uq_overtime_campaign_skill_period", "overtime_plans", type_="unique")
    op.drop_constraint("uq_capacity_campaign_skill_period", "capacity_plans", type_="unique")
    op.drop_constraint("uq_schedule_employee_date", "schedule_entries", type_="unique")
