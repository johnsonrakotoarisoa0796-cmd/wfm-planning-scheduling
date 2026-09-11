"""Tests unitaires — app/services/forecast_service.py (fonctions pures uniquement,
la logique DB est testée dans tests/integration/test_ltf.py).

Les valeurs attendues sont vérifiées contre numpy.busday_count (déjà une
dépendance du projet), une implémentation indépendante du comptage de jours
ouvrés — pas des nombres devinés à la main.
"""

from app.services.forecast_service import working_days_in_month


def test_working_days_in_month_matches_independent_reference():
    # Chaque valeur revérifiée avec numpy.busday_count avant d'écrire ce test.
    assert working_days_in_month(2026, 9) == 22
    assert working_days_in_month(2026, 2) == 20
    assert working_days_in_month(2026, 12) == 23
    assert working_days_in_month(2027, 1) == 21


def test_working_days_in_month_leap_year_february():
    # 2024 est bissextile (29 jours) ; le comptage ne doit pas planter sur le 29.
    assert working_days_in_month(2024, 2) == 21
