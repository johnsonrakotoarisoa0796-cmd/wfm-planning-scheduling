"""Conversions d'unités de temps.

Convention du projet : toute variable numérique porte son unité dans son nom
(ex: aht_seconds, paid_hours, interval_minutes). Les conversions passent
TOUJOURS par ce module — jamais de /60 ou *60 en dur ailleurs dans le code
(règle §39 du cahier des charges).
"""


def seconds_to_minutes(seconds: float) -> float:
    """Convertit des secondes en minutes."""
    return seconds / 60


def minutes_to_seconds(minutes: float) -> float:
    """Convertit des minutes en secondes."""
    return minutes * 60


def minutes_to_hours(minutes: float) -> float:
    """Convertit des minutes en heures."""
    return minutes / 60


def hours_to_minutes(hours: float) -> float:
    """Convertit des heures en minutes."""
    return hours * 60


def hours_to_seconds(hours: float) -> float:
    """Convertit des heures en secondes."""
    return hours * 3600


def seconds_to_hours(seconds: float) -> float:
    """Convertit des secondes en heures."""
    return seconds / 3600
