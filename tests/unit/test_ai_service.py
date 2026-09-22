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
    assert "ne prétends jamais avoir modifié la base" in system
    assert "Analyse la couverture de lundi." in user


def test_ai_instruction_requires_data_only():
    system, _ = build_ai_instruction("report", "", {"forecast": {"forecast_volume": 1200}})
    assert "N'invente aucun chiffre" in system
    assert "forecast_volume" in _
