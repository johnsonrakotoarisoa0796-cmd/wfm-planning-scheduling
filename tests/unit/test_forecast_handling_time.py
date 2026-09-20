from app.schemas.ltf import LTFCreateInput
from app.schemas.stf import STFCreateInput


def test_ltf_handling_time_aliases_forecast_aht():
    data = LTFCreateInput(
        iso_year=2026,
        iso_week=41,
        campaign_id=1,
        skill_id=1,
        forecast_volume=52000,
        forecast_aht_seconds=300,
        aht_required_seconds=300,
        occupancy_required_pct=85,
        service_level_target_pct=80,
        asa_target_seconds=20,
        indoor_shrinkage_pct=10,
        outdoor_shrinkage_pct=5,
    )
    assert data.handling_time_seconds == 300


def test_stf_handling_time_aliases_aht():
    data = STFCreateInput(
        iso_year=2026,
        iso_week=41,
        campaign_id=1,
        skill_id=1,
        volume=53200,
        aht_seconds=310,
        occupancy_pct=85,
        shrinkage_pct=15,
        service_level_target_pct=80,
    )
    assert data.handling_time_seconds == 310
