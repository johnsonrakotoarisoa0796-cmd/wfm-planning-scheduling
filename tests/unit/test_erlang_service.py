"""Tests unitaires — app/services/erlang_service.py.

Le scénario de référence (100 appels / 30 min, AHT 180s) est vérifié contre
une source externe indépendante (hirefinn.ai/tools/erlang-c-calculator),
elle-même recalculée manuellement avant d'écrire ce fichier (voir le
docstring de erlang_service.py) : traffic = 10 Erlangs, 13 agents -> 79.56%
SL, 14 agents -> 88.84% SL et ~7.8s d'ASA. Ce n'est pas juste un
auto-test : les nombres proviennent d'un calculateur tiers.
"""

import math

import pytest

from app.services.erlang_service import (
    RequiredAgentsResult,
    apply_shrinkage,
    average_speed_of_answer_erlang_c,
    erlang_c_probability_of_wait,
    find_required_agents,
    occupancy_from_traffic_pct,
    service_level_erlang_c,
    traffic_intensity_erlangs,
)

# Scénario de référence : 100 appels / 30 min, AHT 180s.
REF_VOLUME = 100
REF_AHT_SECONDS = 180
REF_INTERVAL_SECONDS = 1800
REF_TRAFFIC_ERLANGS = 10.0


# --- Traffic Intensity ---------------------------------------------------------

def test_traffic_intensity_matches_reference_scenario():
    traffic = traffic_intensity_erlangs(REF_VOLUME, REF_AHT_SECONDS, REF_INTERVAL_SECONDS)
    assert traffic == pytest.approx(REF_TRAFFIC_ERLANGS, abs=0.001)


def test_traffic_intensity_zero_volume_is_zero_erlangs():
    assert traffic_intensity_erlangs(0, 180, 1800) == 0.0


def test_traffic_intensity_rejects_non_positive_interval():
    with pytest.raises(ValueError):
        traffic_intensity_erlangs(100, 180, 0)


def test_traffic_intensity_rejects_negative_inputs():
    with pytest.raises(ValueError):
        traffic_intensity_erlangs(-1, 180, 1800)


# --- Erlang C / Service Level / ASA — valeurs de référence vérifiées -----------

def test_service_level_matches_reference_at_13_agents_below_target():
    sl = service_level_erlang_c(13, REF_TRAFFIC_ERLANGS, REF_AHT_SECONDS, answer_time_target_seconds=20)
    assert sl == pytest.approx(79.56, abs=0.05)


def test_service_level_matches_reference_at_14_agents_meets_target():
    sl = service_level_erlang_c(14, REF_TRAFFIC_ERLANGS, REF_AHT_SECONDS, answer_time_target_seconds=20)
    assert sl == pytest.approx(88.84, abs=0.05)


def test_asa_matches_reference_at_14_agents():
    asa = average_speed_of_answer_erlang_c(14, REF_TRAFFIC_ERLANGS, REF_AHT_SECONDS)
    assert asa == pytest.approx(7.84, abs=0.1)


def test_service_level_increases_monotonically_with_more_agents():
    # Ajouter des agents ne peut jamais degrader le service level.
    levels = [
        service_level_erlang_c(n, REF_TRAFFIC_ERLANGS, REF_AHT_SECONDS, 20)
        for n in range(11, 20)
    ]
    assert levels == sorted(levels)


def test_unstable_system_returns_zero_service_level_and_infinite_asa():
    # agents <= traffic : la file d'attente grandit sans limite.
    assert service_level_erlang_c(10, REF_TRAFFIC_ERLANGS, REF_AHT_SECONDS, 20) == 0.0
    assert average_speed_of_answer_erlang_c(10, REF_TRAFFIC_ERLANGS, REF_AHT_SECONDS) == math.inf
    assert erlang_c_probability_of_wait(10, REF_TRAFFIC_ERLANGS) == 1.0


def test_erlang_c_probability_of_wait_between_zero_and_one_when_stable():
    p = erlang_c_probability_of_wait(14, REF_TRAFFIC_ERLANGS)
    assert 0.0 <= p <= 1.0


# --- Occupancy -----------------------------------------------------------------

def test_occupancy_from_traffic_pct():
    # 10 Erlangs de trafic / 14 agents.
    occ = occupancy_from_traffic_pct(REF_TRAFFIC_ERLANGS, 14)
    assert occ == pytest.approx(71.43, abs=0.01)


def test_occupancy_from_traffic_pct_zero_agents_returns_zero():
    assert occupancy_from_traffic_pct(REF_TRAFFIC_ERLANGS, 0) == 0.0


# --- find_required_agents — dimensionnement complet -----------------------------

def test_find_required_agents_matches_reference_scenario_needs_14():
    result = find_required_agents(
        volume_contacts=REF_VOLUME,
        aht_seconds=REF_AHT_SECONDS,
        interval_seconds=REF_INTERVAL_SECONDS,
        service_level_target_pct=80.0,
        answer_time_target_seconds=20.0,
    )
    assert isinstance(result, RequiredAgentsResult)
    assert result.traffic_erlangs == pytest.approx(10.0, abs=0.001)
    assert result.net_required_hc == 14
    assert result.achieved_service_level_pct == pytest.approx(88.84, abs=0.05)
    assert result.achieved_service_level_pct >= 80.0


def test_find_required_agents_13_agents_would_have_missed_target():
    # Verification croisee : le HC juste en-dessous ne doit PAS satisfaire la cible.
    sl_at_13 = service_level_erlang_c(13, REF_TRAFFIC_ERLANGS, REF_AHT_SECONDS, 20)
    assert sl_at_13 < 80.0


def test_find_required_agents_zero_volume_needs_zero_agents():
    result = find_required_agents(
        volume_contacts=0,
        aht_seconds=REF_AHT_SECONDS,
        interval_seconds=REF_INTERVAL_SECONDS,
        service_level_target_pct=80.0,
        answer_time_target_seconds=20.0,
    )
    assert result.net_required_hc == 0
    assert result.traffic_erlangs == 0.0


def test_find_required_agents_higher_service_level_target_needs_more_agents():
    result_80 = find_required_agents(
        REF_VOLUME, REF_AHT_SECONDS, REF_INTERVAL_SECONDS,
        service_level_target_pct=80.0, answer_time_target_seconds=20.0,
    )
    result_95 = find_required_agents(
        REF_VOLUME, REF_AHT_SECONDS, REF_INTERVAL_SECONDS,
        service_level_target_pct=95.0, answer_time_target_seconds=20.0,
    )
    assert result_95.net_required_hc > result_80.net_required_hc


def test_find_required_agents_respects_occupancy_cap():
    # Sans cap d'occupancy : 14 agents suffisent (occupancy ~71%).
    without_cap = find_required_agents(
        REF_VOLUME, REF_AHT_SECONDS, REF_INTERVAL_SECONDS,
        service_level_target_pct=80.0, answer_time_target_seconds=20.0,
    )
    # Avec un plafond d'occupancy tres bas (50%), il faut plus d'agents
    # meme si le Service Level serait deja atteint avec moins.
    with_cap = find_required_agents(
        REF_VOLUME, REF_AHT_SECONDS, REF_INTERVAL_SECONDS,
        service_level_target_pct=80.0, answer_time_target_seconds=20.0,
        occupancy_target_pct=50.0,
    )
    assert with_cap.net_required_hc > without_cap.net_required_hc
    assert with_cap.achieved_occupancy_pct <= 50.0


def test_find_required_agents_rejects_non_positive_interval():
    with pytest.raises(ValueError):
        find_required_agents(100, 180, 0, 80.0, 20.0)


# --- Shrinkage : Net -> Gross Required HC ---------------------------------------

def test_apply_shrinkage_matches_brief_definition():
    # Net=14, shrinkage 30% -> Gross = 14 / 0.7 = 20
    gross = apply_shrinkage(net_required_hc=14, shrinkage_pct=30)
    assert gross == pytest.approx(20.0, abs=0.01)


def test_apply_shrinkage_zero_shrinkage_is_identity():
    assert apply_shrinkage(net_required_hc=14, shrinkage_pct=0) == pytest.approx(14.0)


def test_apply_shrinkage_rejects_100_percent_or_more():
    with pytest.raises(ValueError):
        apply_shrinkage(net_required_hc=14, shrinkage_pct=100)


def test_apply_shrinkage_rejects_negative_shrinkage():
    with pytest.raises(ValueError):
        apply_shrinkage(net_required_hc=14, shrinkage_pct=-5)
