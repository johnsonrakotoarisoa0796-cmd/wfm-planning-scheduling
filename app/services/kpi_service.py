"""Moteur KPI centralisé.

Toutes les formules WFM vivent ici — aucun calcul métier dans les templates
Jinja ni le JavaScript (règle §11 du cahier des charges). Chaque fonction
est pure (mêmes entrées -> mêmes sorties), sans dépendance DB ni FastAPI,
ce qui les rend triviales à tester unitairement.

Convention d'unités (§39) : chaque paramètre porte son unité dans son nom
(aht_seconds, paid_hours, volume_contacts...). Les conversions passent par
app/core/units.py, jamais de /60 ou *60 en dur ici.

Politique de division par zéro : un KPI "taux" (AHT, Occupancy, Service
Level, ASA, Shrinkage %...) retourne 0.0 quand le dénominateur est nul ou
négatif (absence de volume/heures sur la période), plutôt que de lever une
exception — un écran WFM doit pouvoir afficher "0%" pour une période sans
activité sans planter le dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


def _safe_ratio(numerator: float, denominator: float) -> float:
    """Division protégée : 0.0 si le dénominateur est nul ou négatif."""
    if denominator <= 0:
        return 0.0
    return numerator / denominator


# --- Handle Time / AHT (§12, §13) -------------------------------------------

def handle_time_seconds(talk_time_seconds: float, hold_time_seconds: float, acw_seconds: float) -> float:
    """Handle Time = Talk Time + Hold Time + ACW."""
    return talk_time_seconds + hold_time_seconds + acw_seconds


def average_handle_time_seconds(total_handle_time_seconds: float, handled_contacts: float) -> float:
    """AHT = Total Handle Time / Handled Contacts. 0.0 si aucun contact traité."""
    return _safe_ratio(total_handle_time_seconds, handled_contacts)


def aht_variance_seconds(observed_aht_seconds: float, aht_required_seconds: float) -> float:
    """Écart en secondes entre un AHT observé (forecast ou actual) et l'AHT required."""
    return observed_aht_seconds - aht_required_seconds


def aht_variance_pct(observed_aht_seconds: float, aht_required_seconds: float) -> float:
    """Écart en % entre un AHT observé et l'AHT required."""
    return _safe_ratio(observed_aht_seconds - aht_required_seconds, aht_required_seconds) * 100


# --- Occupancy (§17) ----------------------------------------------------------

def occupancy_pct(handle_time_hours: float, waiting_hours: float) -> float:
    """Occupancy = temps de traitement / (temps de traitement + temps d'attente).

    0.0 si l'agent n'a ni traité ni attendu (pas de staffing sur la période).
    """
    return _safe_ratio(handle_time_hours, handle_time_hours + waiting_hours) * 100


# --- Service Level / ASA (§14, §16) -------------------------------------------

def service_level_pct(answered_within_threshold: float, offered: float, excluded_contacts: float = 0.0) -> float:
    """Service Level = répondu <= seuil / (offered - excluded) x 100.

    excluded_contacts couvre les exclusions configurables (ex: Short
    Abandon) définies au niveau du SLAProfile de la campagne.
    """
    eligible = offered - excluded_contacts
    return _safe_ratio(answered_within_threshold, eligible) * 100


def average_speed_of_answer_seconds(total_wait_time_seconds: float, answered_contacts: float) -> float:
    """ASA = temps d'attente total / contacts répondus."""
    return _safe_ratio(total_wait_time_seconds, answered_contacts)


def abandon_rate_pct(abandoned_contacts: float, offered_contacts: float) -> float:
    """Abandon Rate = contacts abandonnés / contacts offerts x 100 (§10)."""
    return _safe_ratio(abandoned_contacts, offered_contacts) * 100


# --- Shrinkage / Paid / Productive / Production Hours (§19-§22, §24) ---------

def shrinkage_pct(total_shrinkage_hours: float, paid_hours: float) -> float:
    """Shrinkage % = Total Shrinkage Hours / Paid Hours x 100."""
    return _safe_ratio(total_shrinkage_hours, paid_hours) * 100


def paid_hours(employee_count: float, daily_hours: float, working_days: float) -> float:
    """Paid Hours = effectif x heures/jour x jours travaillés.

    daily_hours et working_days doivent toujours venir de la configuration
    (app/core/config.py ou ConfigParameter en base), jamais d'une valeur en
    dur (règle §19).
    """
    return employee_count * daily_hours * working_days


def workload_hours(volume_contacts: float, aht_seconds: float) -> float:
    """Charge de travail totale (heures) = Volume x AHT / 3600 (secondes -> heures)."""
    return (volume_contacts * aht_seconds) / 3600


def required_hc_aggregate(
    workload_hours_value: float,
    available_hours_per_agent: float,
    occupancy_target_pct: float,
) -> float:
    """Net Required HC agrégé (niveau LTF/STF) = charge de travail totale /
    (heures disponibles par agent x occupancy cible).

    À la différence de erlang_service.find_required_agents (qui résout la
    file d'attente sur un intervalle court où l'arrivée des appels minute
    par minute compte), cette formule agrégée convient à un horizon
    mensuel/hebdomadaire : c'est le ratio standard de l'industrie pour le
    capacity planning long terme. Le dimensionnement Erlang C précis
    n'intervient qu'au niveau Daily/Intraday (commit 08).
    """
    available_capacity_hours = available_hours_per_agent * (occupancy_target_pct / 100)
    return _safe_ratio(workload_hours_value, available_capacity_hours)


def productive_hours(paid_hours_value: float, total_shrinkage_hours: float) -> float:
    """Productive Hours = Paid Hours - Total Shrinkage Hours."""
    return paid_hours_value - total_shrinkage_hours


def production_hours(productive_hours_value: float, waiting_hours: float) -> float:
    """Production Hours = Productive Hours - Waiting Time.

    Définition retenue et documentée dans WFM_ARCHITECTURE_PLAN.md (section
    5) faute de précision du client sur ce point ; l'autre convention
    possible (Waiting Time compté à part, sans venir en déduction du
    Productive Hours) ne nécessiterait de changer que cette seule fonction.
    """
    return productive_hours_value - waiting_hours


def waiting_time_pct(waiting_hours: float, productive_hours_value: float) -> float:
    """Waiting % = Waiting Hours / Productive Hours x 100."""
    return _safe_ratio(waiting_hours, productive_hours_value) * 100


# --- Forecast Accuracy (§46) ---------------------------------------------------

def forecast_variance(forecast: float, actual: float) -> float:
    """Variance = Actual - Forecast."""
    return actual - forecast


def forecast_variance_pct(forecast: float, actual: float) -> float:
    """Variance % = (Actual - Forecast) / Forecast x 100."""
    return _safe_ratio(actual - forecast, forecast) * 100


def forecast_accuracy_pct(forecast: float, actual: float) -> float:
    """Forecast Accuracy = (1 - |Forecast - Actual| / Actual) x 100.

    0.0 si actual == 0 : sans activité réelle, la précision de la prévision
    n'est pas mesurable, on ne peut pas afficher un pourcentage trompeur.
    """
    if actual == 0:
        return 0.0
    return (1 - abs(forecast - actual) / actual) * 100


# --- Staffing Gap (§32) ---------------------------------------------------------

class StaffingStatus(str, Enum):
    UNDERSTAFFED = "understaffed"
    BALANCED = "balanced"
    OVERSTAFFED = "overstaffed"


def staffing_gap(available_hc: float, required_hc: float) -> float:
    """Gap = Available/Scheduled HC - Required HC."""
    return available_hc - required_hc


def overtime_required_hours(required_hours: float, available_hours: float) -> float:
    """OT Required = max(0, Required Hours - Available Hours) (§27).

    Jamais négatif : un excédent d'heures disponibles est un problème de
    sur-staffing (Capacity Planning, §31), pas un OT "négatif".
    """
    return max(0.0, required_hours - available_hours)


def overtime_variance(required_ot_hours: float, actual_ot_hours: float) -> float:
    """OT Variance = Actual OT - Required OT (§30).

    Ne jamais confondre le besoin théorique (Required) avec l'OT
    réellement réalisé (Actual) — ce sont deux données distinctes,
    stockées séparément (voir OvertimePlan.ot_required_hours /
    ot_actual_hours).
    """
    return actual_ot_hours - required_ot_hours


def projected_headcount(
    current_hc: float,
    hiring: float,
    transfers_in: float,
    transfers_out: float,
    attrition_pct: float,
    absenteeism_pct: float,
) -> float:
    """Future HC = Current HC + Hiring + Transfers In - Transfers Out
    - Attrition - Absenteeism (§31).

    attrition_pct et absenteeism_pct sont des taux (%) appliqués au Current
    HC (perte attendue sur l'effectif actuel), pas des valeurs absolues.
    """
    losses = current_hc * (attrition_pct / 100) + current_hc * (absenteeism_pct / 100)
    return current_hc + hiring + transfers_in - transfers_out - losses


def staffing_status(gap: float, balanced_tolerance_hc: float = 0.5) -> StaffingStatus:
    """Classifie un écart de staffing en overstaffed/balanced/understaffed.

    balanced_tolerance_hc : marge (en HC) considérée comme "équilibrée"
    plutôt que sur/sous-staffée, pour éviter qu'un écart de 0.1 HC bascule
    le statut d'un extrême à l'autre.
    """
    if gap > balanced_tolerance_hc:
        return StaffingStatus.OVERSTAFFED
    if gap < -balanced_tolerance_hc:
        return StaffingStatus.UNDERSTAFFED
    return StaffingStatus.BALANCED


# --- Statut générique KPI pour le Dashboard (§5 : vert/orange/rouge) -----------

class KPIStatus(str, Enum):
    ON_TARGET = "on_target"
    WARNING = "warning"
    CRITICAL = "critical"


def kpi_variance(actual: float, target: float) -> float:
    """Écart brut Actual - Target."""
    return actual - target


def kpi_status(
    actual: float,
    target: float,
    on_target_tolerance_pct: float = 2.0,
    critical_tolerance_pct: float = 10.0,
    higher_is_better: bool = True,
) -> KPIStatus:
    """Statut d'un KPI par rapport à sa cible, pour l'affichage Dashboard (§5).

    higher_is_better=True pour un KPI où dépasser la cible est positif
    (Service Level, Occupancy...) ; False pour un KPI où dépasser la cible
    est négatif (AHT, Shrinkage, ASA...).

    - à moins de on_target_tolerance_pct de la cible (ou mieux) -> ON_TARGET
    - au-delà, jusqu'à critical_tolerance_pct -> WARNING
    - au-delà de critical_tolerance_pct -> CRITICAL
    """
    if target == 0:
        return KPIStatus.ON_TARGET if actual == 0 else KPIStatus.CRITICAL

    deviation_pct = (actual - target) / target * 100
    if not higher_is_better:
        deviation_pct = -deviation_pct

    if deviation_pct >= -on_target_tolerance_pct:
        return KPIStatus.ON_TARGET
    if deviation_pct >= -critical_tolerance_pct:
        return KPIStatus.WARNING
    return KPIStatus.CRITICAL


@dataclass(frozen=True)
class KPIComparison:
    """Regroupe Actual/Target/Variance/Status — la forme exacte des tableaux
    KPI demandés en §5 (Dashboard) et §44 (tableaux Forecast/Actual/Target)."""

    actual: float
    target: float
    variance: float
    status: KPIStatus


def evaluate_kpi(
    actual: float,
    target: float,
    on_target_tolerance_pct: float = 2.0,
    critical_tolerance_pct: float = 10.0,
    higher_is_better: bool = True,
) -> KPIComparison:
    """Construit un KPIComparison complet (actual/target/variance/status)."""
    return KPIComparison(
        actual=actual,
        target=target,
        variance=kpi_variance(actual, target),
        status=kpi_status(actual, target, on_target_tolerance_pct, critical_tolerance_pct, higher_is_better),
    )
