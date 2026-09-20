"""Tests unitaires — app/services/kpi_service.py.

Chaque formule est testée sur un cas nominal ET sur ses cas limites
(dénominateur nul, valeurs négatives) — un moteur KPI qui plante sur une
période sans activité casserait tout le dashboard.
"""

import pytest

from app.services.kpi_service import (
    KPIComparison,
    KPIStatus,
    StaffingStatus,
    abandon_rate_pct,
    aht_variance_pct,
    aht_variance_seconds,
    average_handle_time_seconds,
    average_speed_of_answer_seconds,
    evaluate_kpi,
    forecast_accuracy_pct,
    forecast_variance,
    forecast_variance_pct,
    handle_time_seconds,
    kpi_status,
    kpi_variance,
    occupancy_pct,
    overtime_required_hours,
    overtime_variance,
    paid_hours,
    production_hours,
    productive_hours,
    projected_headcount,
    projected_available_headcount,
    service_level_pct,
    shrinkage_pct,
    staffing_gap,
    staffing_status,
    waiting_time_pct,
)


# --- Handle Time / AHT ---------------------------------------------------------

def test_handle_time_seconds():
    assert handle_time_seconds(talk_time_seconds=200, hold_time_seconds=30, acw_seconds=90) == 320


def test_average_handle_time_seconds():
    assert average_handle_time_seconds(total_handle_time_seconds=32000, handled_contacts=100) == 320


def test_average_handle_time_seconds_zero_contacts_returns_zero():
    assert average_handle_time_seconds(total_handle_time_seconds=0, handled_contacts=0) == 0.0


def test_aht_variance_seconds():
    assert aht_variance_seconds(observed_aht_seconds=337, aht_required_seconds=310) == 27


def test_aht_variance_pct():
    result = aht_variance_pct(observed_aht_seconds=341, aht_required_seconds=310)
    assert result == pytest.approx(10.0, abs=0.01)


def test_aht_variance_pct_zero_required_returns_zero():
    assert aht_variance_pct(observed_aht_seconds=300, aht_required_seconds=0) == 0.0


# --- Occupancy -------------------------------------------------------------------

def test_occupancy_pct_matches_brief_example():
    # §17 : Occupancy Required 85%, Occupancy Actual 89%
    result = occupancy_pct(handle_time_hours=89, waiting_hours=11)
    assert result == pytest.approx(89.0, abs=0.01)


def test_occupancy_pct_zero_staffed_returns_zero():
    assert occupancy_pct(handle_time_hours=0, waiting_hours=0) == 0.0


# --- Service Level / ASA ----------------------------------------------------------

def test_service_level_pct_basic():
    result = service_level_pct(answered_within_threshold=8000, offered=10000)
    assert result == pytest.approx(80.0, abs=0.01)


def test_service_level_pct_with_exclusions():
    # Sans exclusion : 8000/10000 = 80%. Avec 500 exclus : 8000/9500 > 80%.
    without_exclusion = service_level_pct(answered_within_threshold=8000, offered=10000)
    with_exclusion = service_level_pct(answered_within_threshold=8000, offered=10000, excluded_contacts=500)
    assert with_exclusion > without_exclusion


def test_service_level_pct_zero_offered_returns_zero():
    assert service_level_pct(answered_within_threshold=0, offered=0) == 0.0


def test_average_speed_of_answer_seconds():
    assert average_speed_of_answer_seconds(total_wait_time_seconds=4000, answered_contacts=200) == 20


def test_average_speed_of_answer_seconds_zero_answered_returns_zero():
    assert average_speed_of_answer_seconds(total_wait_time_seconds=0, answered_contacts=0) == 0.0


def test_abandon_rate_pct():
    assert abandon_rate_pct(abandoned_contacts=50, offered_contacts=1000) == pytest.approx(5.0)


def test_abandon_rate_pct_zero_offered_returns_zero():
    assert abandon_rate_pct(abandoned_contacts=0, offered_contacts=0) == 0.0


# --- Shrinkage / Paid / Productive / Production Hours -----------------------------

def test_shrinkage_pct_matches_brief_definition():
    # §24 : Shrinkage % = Total Shrinkage Hours / Paid Hours x 100
    result = shrinkage_pct(total_shrinkage_hours=100, paid_hours=400)
    assert result == pytest.approx(25.0, abs=0.01)


def test_shrinkage_pct_zero_paid_hours_returns_zero():
    assert shrinkage_pct(total_shrinkage_hours=0, paid_hours=0) == 0.0


def test_paid_hours_matches_brief_base_rule():
    # §19 : 5 jours x 8 heures = 40 heures / semaine, pour 1 employe.
    assert paid_hours(employee_count=1, daily_hours=8, working_days=5) == 40


def test_paid_hours_scales_with_team_size():
    assert paid_hours(employee_count=10, daily_hours=8, working_days=5) == 400


def test_productive_hours():
    assert productive_hours(paid_hours_value=400, total_shrinkage_hours=100) == 300


def test_production_hours():
    assert production_hours(productive_hours_value=300, waiting_hours=40) == 260


def test_waiting_time_pct():
    result = waiting_time_pct(waiting_hours=40, productive_hours_value=300)
    assert result == pytest.approx(13.33, abs=0.01)


def test_waiting_time_pct_zero_productive_hours_returns_zero():
    assert waiting_time_pct(waiting_hours=0, productive_hours_value=0) == 0.0


# --- Forecast Accuracy --------------------------------------------------------------

def test_forecast_variance_matches_brief_example():
    # §46 : Forecast 10000, Actual 10500 -> Variance +500
    assert forecast_variance(forecast=10000, actual=10500) == 500


def test_forecast_variance_pct_matches_brief_example():
    result = forecast_variance_pct(forecast=10000, actual=10500)
    assert result == pytest.approx(5.0, abs=0.01)


def test_forecast_accuracy_pct_perfect_forecast():
    assert forecast_accuracy_pct(forecast=10000, actual=10000) == pytest.approx(100.0)


def test_forecast_accuracy_pct_matches_variance_example():
    # Ecart de 5% -> Accuracy de 95%.
    result = forecast_accuracy_pct(forecast=10000, actual=10500)
    assert result == pytest.approx(95.24, abs=0.01)


def test_forecast_accuracy_pct_zero_actual_returns_zero():
    assert forecast_accuracy_pct(forecast=100, actual=0) == 0.0


# --- Staffing Gap ---------------------------------------------------------------------

def test_staffing_gap_positive_is_overstaffed():
    gap = staffing_gap(available_hc=30, required_hc=25)
    assert gap == 5
    assert staffing_status(gap) == StaffingStatus.OVERSTAFFED


def test_staffing_gap_negative_is_understaffed():
    gap = staffing_gap(available_hc=27, required_hc=32)
    assert gap == -5
    assert staffing_status(gap) == StaffingStatus.UNDERSTAFFED


def test_staffing_gap_zero_is_balanced():
    assert staffing_status(0) == StaffingStatus.BALANCED


def test_staffing_status_respects_tolerance():
    # Petit ecart (0.3 HC), en dessous de la tolerance par defaut (0.5) -> balanced.
    assert staffing_status(0.3) == StaffingStatus.BALANCED
    assert staffing_status(-0.3) == StaffingStatus.BALANCED
    # Ecart plus large -> statut tranche.
    assert staffing_status(0.6) == StaffingStatus.OVERSTAFFED
    assert staffing_status(-0.6) == StaffingStatus.UNDERSTAFFED


def test_projected_headcount_matches_brief_formula():
    # Future HC = Current + Hiring + Transfers In - Transfers Out - Attrition - Absenteeism
    result = projected_headcount(
        current_hc=100, hiring=5, transfers_in=2, transfers_out=3,
        attrition_pct=5,
    )
    # L'absentéisme ne réduit pas le headcount, uniquement la disponibilité.
    assert result == pytest.approx(100 + 5 + 2 - 3 - 5)
    assert projected_available_headcount(projected_hc=result, absenteeism_pct=3) == pytest.approx(result * 0.97)


def test_projected_headcount_no_movement_with_zero_rates():
    result = projected_headcount(
        current_hc=50, hiring=0, transfers_in=0, transfers_out=0,
        attrition_pct=0, absenteeism_pct=0,
    )
    assert result == 50


def test_overtime_required_hours_matches_brief_example():
    # §27 : Demand Required 820h, Available 780h -> OT Required 40h.
    assert overtime_required_hours(required_hours=820, available_hours=780) == 40


def test_overtime_required_hours_never_negative_when_overstaffed():
    assert overtime_required_hours(required_hours=700, available_hours=780) == 0.0


def test_overtime_variance_matches_brief_example():
    # §30 : Required OT 80h, Actual OT 65h -> OT Gap -15h.
    assert overtime_variance(required_ot_hours=80, actual_ot_hours=65) == -15


# --- Statut générique KPI (Dashboard) ---------------------------------------------------

def test_kpi_variance():
    assert kpi_variance(actual=76.4, target=80) == pytest.approx(-3.6, abs=0.01)


def test_kpi_status_on_target_when_meeting_or_exceeding():
    # Service Level : plus haut = mieux.
    assert kpi_status(actual=82, target=80, higher_is_better=True) == KPIStatus.ON_TARGET


def test_kpi_status_matches_brief_below_target_example():
    # §5 : Target 80%, Actual 76.4% -> Variance -3.6 pts -> "Below Target".
    # -3.6/80 = -4.5%, au-dela de la tolerance par defaut (2%) mais en-deca
    # du seuil critique (10%) -> WARNING (pas encore critique).
    status = kpi_status(actual=76.4, target=80, higher_is_better=True)
    assert status == KPIStatus.WARNING


def test_kpi_status_critical_when_far_below_target():
    status = kpi_status(actual=60, target=80, higher_is_better=True)
    assert status == KPIStatus.CRITICAL


def test_kpi_status_higher_is_better_false_for_aht_like_kpis():
    # AHT : plus bas = mieux. Actual sous la cible -> on_target, meme si
    # "actual < target" (ce qui serait "warning" pour un KPI higher_is_better).
    assert kpi_status(actual=300, target=310, higher_is_better=False) == KPIStatus.ON_TARGET
    # Actual tres au-dessus de la cible (AHT trop eleve) -> critical.
    assert kpi_status(actual=360, target=310, higher_is_better=False) == KPIStatus.CRITICAL


def test_kpi_status_zero_target_edge_case():
    assert kpi_status(actual=0, target=0) == KPIStatus.ON_TARGET
    assert kpi_status(actual=5, target=0) == KPIStatus.CRITICAL


def test_evaluate_kpi_bundles_actual_target_variance_status():
    result = evaluate_kpi(actual=76.4, target=80, higher_is_better=True)
    assert isinstance(result, KPIComparison)
    assert result.actual == 76.4
    assert result.target == 80
    assert result.variance == pytest.approx(-3.6, abs=0.01)
    assert result.status == KPIStatus.WARNING
