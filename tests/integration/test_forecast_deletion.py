from datetime import date, time

from sqlmodel import Session, select

from app.models.forecast import ForecastVersion, LTFForecast, STFForecast
from app.models.intraday import IntervalForecast
from app.schemas.ltf import LTFCreateInput
from app.schemas.stf import STFCreateInput
from app.services import forecast_service


def test_delete_ltf_with_stf_requires_cascade(engine, reference_data):
    with Session(engine) as session:
        ltf = forecast_service.create_ltf_forecast(
            session,
            LTFCreateInput(
                year=2026,
                month=9,
                campaign_id=reference_data["campaign_id"],
                skill_id=reference_data["skill_id"],
                forecast_volume=42000,
                forecast_aht_seconds=320,
                aht_required_seconds=310,
                occupancy_required_pct=85,
                service_level_target_pct=80,
                asa_target_seconds=20,
                indoor_shrinkage_pct=18,
                outdoor_shrinkage_pct=7,
            ),
            created_by_user_id=None,
        )
        stf = forecast_service.create_stf_forecast(
            session,
            STFCreateInput(
                iso_year=2026,
                iso_week=37,
                campaign_id=reference_data["campaign_id"],
                skill_id=reference_data["skill_id"],
                volume=44500,
                aht_seconds=335,
                occupancy_pct=86,
                shrinkage_pct=28,
                service_level_target_pct=80,
            ),
            created_by_user_id=None,
        )

        try:
            forecast_service.delete_ltf_forecast(session, ltf.id, cascade=False)
        except ValueError as exc:
            assert "STF" in str(exc)
        else:
            raise AssertionError("LTF deletion must require cascade while a STF depends on it")

        forecast_service.delete_ltf_forecast(session, ltf.id, cascade=True)

        assert session.get(LTFForecast, ltf.id) is None
        assert session.get(STFForecast, stf.id) is None
        assert session.get(ForecastVersion, ltf.forecast_version_id) is None
        assert session.get(ForecastVersion, stf.forecast_version_id) is None


def test_delete_stf_with_intraday_requires_cascade(engine, reference_data):
    with Session(engine) as session:
        ltf = forecast_service.create_ltf_forecast(
            session,
            LTFCreateInput(
                year=2026,
                month=9,
                campaign_id=reference_data["campaign_id"],
                skill_id=reference_data["skill_id"],
                forecast_volume=42000,
                forecast_aht_seconds=320,
                aht_required_seconds=310,
                occupancy_required_pct=85,
                service_level_target_pct=80,
                asa_target_seconds=20,
                indoor_shrinkage_pct=18,
                outdoor_shrinkage_pct=7,
            ),
            created_by_user_id=None,
        )
        stf = forecast_service.create_stf_forecast(
            session,
            STFCreateInput(
                iso_year=2026,
                iso_week=37,
                campaign_id=reference_data["campaign_id"],
                skill_id=reference_data["skill_id"],
                volume=44500,
                aht_seconds=335,
                occupancy_pct=86,
                shrinkage_pct=28,
                service_level_target_pct=80,
            ),
            created_by_user_id=None,
        )

        interval = IntervalForecast(
            date=date(2026, 9, 7),
            interval_start=time(10, 0),
            interval_end=time(10, 30),
            campaign_id=reference_data["campaign_id"],
            skill_id=reference_data["skill_id"],
            forecast_volume=100,
            forecast_aht_seconds=335,
            required_hc=2,
        )
        session.add(interval)
        session.commit()

        try:
            forecast_service.delete_stf_forecast(session, stf.id, cascade=False)
        except ValueError as exc:
            assert "Daily/Intraday" in str(exc)
        else:
            raise AssertionError("STF deletion must require cascade while Intraday exists")

        forecast_service.delete_stf_forecast(session, stf.id, cascade=True)

        assert session.get(STFForecast, stf.id) is None
        assert session.get(ForecastVersion, stf.forecast_version_id) is None
        assert session.exec(select(IntervalForecast)).first() is None
        assert session.get(LTFForecast, ltf.id) is not None
