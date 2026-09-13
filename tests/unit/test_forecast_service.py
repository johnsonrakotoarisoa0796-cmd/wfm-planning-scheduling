"""Tests unitaires — app/services/forecast_service.py (fonctions pures uniquement,
la logique DB est testée dans tests/integration/test_ltf.py).

Les valeurs attendues sont vérifiées contre numpy.busday_count (déjà une
dépendance du projet), une implémentation indépendante du comptage de jours
ouvrés — pas des nombres devinés à la main.
"""

from datetime import date

import pytest

from app.models.forecast import LTFForecast, STFForecast
from app.services.forecast_service import compare_ltf_stf, count_weekdays_in_range, working_days_in_month


def test_working_days_in_month_matches_independent_reference():
    # Chaque valeur revérifiée avec numpy.busday_count avant d'écrire ce test.
    assert working_days_in_month(2026, 9) == 22
    assert working_days_in_month(2026, 2) == 20
    assert working_days_in_month(2026, 12) == 23
    assert working_days_in_month(2027, 1) == 21


def test_working_days_in_month_leap_year_february():
    # 2024 est bissextile (29 jours) ; le comptage ne doit pas planter sur le 29.
    assert working_days_in_month(2024, 2) == 21


def test_count_weekdays_in_range_single_full_week():
    # Lundi 7 septembre 2026 a dimanche 13 septembre 2026 -> 5 jours ouvres.
    assert count_weekdays_in_range(date(2026, 9, 7), date(2026, 9, 13)) == 5


def test_count_weekdays_in_range_single_weekday():
    assert count_weekdays_in_range(date(2026, 9, 7), date(2026, 9, 7)) == 1  # lundi


def test_count_weekdays_in_range_single_weekend_day():
    assert count_weekdays_in_range(date(2026, 9, 12), date(2026, 9, 12)) == 0  # samedi


def test_count_weekdays_in_range_matches_working_days_in_month():
    # working_days_in_month delegue desormais a count_weekdays_in_range :
    # les deux doivent rester coherents pour un mois complet.
    assert count_weekdays_in_range(date(2026, 9, 1), date(2026, 9, 30)) == working_days_in_month(2026, 9)


def test_count_weekdays_in_range_rejects_end_before_start():
    with pytest.raises(ValueError):
        count_weekdays_in_range(date(2026, 9, 10), date(2026, 9, 1))


# --- compare_ltf_stf : reproduit exactement l'exemple chiffré du §8 --------------

def test_compare_ltf_stf_matches_brief_worked_example():
    """Reproduit tel quel le tableau d'exemple du cahier des charges (§8) :

        Volume       LTF 42,000   STF 44,500   Variance +2,500
        AHT          LTF 320      STF 335      Variance +15
        Occupancy    LTF 85%      STF 86%      Variance +1 pt
        Shrinkage    LTF 25%      STF 28%      Variance +3 pts
        Required HC  LTF 98       STF 108      Variance +10
    """
    ltf = LTFForecast(
        forecast_version_id=1, year=2026, month=9, campaign_id=1, skill_id=1,
        forecast_volume=42000, forecast_aht_seconds=320, occupancy_required_pct=85,
        total_shrinkage_pct=25, service_level_target_pct=80, headcount_required=98,
    )
    stf = STFForecast(
        forecast_version_id=2, iso_year=2026, iso_week=37, week_start_date=date(2026, 9, 7),
        campaign_id=1, skill_id=1,
        volume=44500, aht_seconds=335, occupancy_pct=86, shrinkage_pct=28,
        service_level_target_pct=80, headcount_required=108,
    )

    rows = {row.metric: row for row in compare_ltf_stf(ltf, stf)}

    assert rows["Volume"].adjustment == 2500
    assert rows["AHT"].adjustment == 15
    assert rows["Occupancy"].adjustment == pytest.approx(1.0)
    assert rows["Shrinkage"].adjustment == pytest.approx(3.0)
    assert rows["Headcount Required"].adjustment == 10

    # Adjustment % = (STF - LTF) / LTF x 100, verifie sur le Volume.
    assert rows["Volume"].adjustment_pct == pytest.approx(2500 / 42000 * 100, abs=0.01)


def test_compare_ltf_stf_negative_adjustment_when_stf_below_ltf():
    ltf = LTFForecast(
        forecast_version_id=1, year=2026, month=9, campaign_id=1, skill_id=1,
        forecast_volume=42000, forecast_aht_seconds=320,
    )
    stf = STFForecast(
        forecast_version_id=2, iso_year=2026, iso_week=37, week_start_date=date(2026, 9, 7),
        campaign_id=1, skill_id=1,
        volume=39000, aht_seconds=320,
    )
    rows = {row.metric: row for row in compare_ltf_stf(ltf, stf)}
    assert rows["Volume"].adjustment == -3000
    assert rows["Volume"].adjustment_pct < 0
