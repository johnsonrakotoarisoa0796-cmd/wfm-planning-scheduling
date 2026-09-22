from app.services.ai_service import _extract_content, build_ai_instruction


def test_ai_extracts_string_content():
    payload = {"choices": [{"message": {"content": " Analyse WFM. "}}]}
    assert _extract_content(payload) == "Analyse WFM."


def test_ai_extracts_multimodal_text_content():
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "Priorité 1. "},
                        {"type": "text", "text": "Sous-staffing."},
                    ]
                }
            }
        ]
    }
    assert _extract_content(payload) == "Priorité 1. Sous-staffing."


def test_ai_instruction_keeps_human_control():
    system, user = build_ai_instruction(
        "scheduling",
        "Analyse la couverture de lundi.",
        {"staffing": {"required_hc_hours": 80, "scheduled_hc_hours": 70}},
    )
    assert "Ne prétends jamais avoir modifié la base" in system
    assert "Analyse la couverture de lundi." in user


def test_ai_instruction_requires_data_only():
    system, _ = build_ai_instruction("report", "", {"forecast": {"forecast_volume": 1200}})
    assert "N'invente aucun chiffre" in system
    assert "forecast_volume" in _


from app.services.ai_service import build_free_analysis


def test_free_analysis_does_not_need_ai_provider():
    snapshot = {
        "period": {"start": "2026-09-21", "end": "2026-09-27"},
        "scope": {"campaign": "Support FR", "skill": "Phone"},
        "forecast": {
            "forecast_volume": 1000.0,
            "actual_volume": 1150.0,
            "volume_delta": 150.0,
            "actual_aht_seconds": 300.0,
            "service_level_pct": 75.0,
            "asa_seconds": 28.0,
            "occupancy_pct": 92.0,
            "abandon_rate_pct": 6.0,
        },
        "staffing": {
            "required_hc_hours": 100.0,
            "scheduled_hc_hours": 90.0,
            "actual_hc_hours": 88.0,
            "scheduled_gap_hours": -10.0,
            "actual_gap_hours": -12.0,
        },
        "workforce": {
            "active_agents": 20,
            "schedule_entries": 100,
            "day_off_entries": 20,
            "absence_records": 3,
        },
        "recruitment": {
            "active_cohorts": 1,
            "planned_hc": 10,
            "training_hc": 2,
            "nesting_hc": 3,
            "production_hc": 5,
        },
    }
    result = build_free_analysis(
        mode="report",
        user_request="Fais le report de la semaine.",
        snapshot=snapshot,
    )
    assert "Report WFM gratuit" in result
    assert "1150.0" in result
    assert "Sous-planification" in result
    assert "Service Level moyen sous 80%" in result
    assert "3 enregistrement(s) d'absence" in result
