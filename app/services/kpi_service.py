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
    """Paid Hours = effectif x heures/jour x jours travaillés."""
    if employee_count < 0 or daily_hours < 0 or working_days < 0:
        raise ValueError("employee_count, daily_hours et working_days doivent être >= 0.")
    return employee_count * daily_hours * working_days


def workload_hours(volume_contacts: float, aht_seconds: float) -> float:
    """Charge de travail totale = Volume x AHT / 3600."""
    if volume_contacts < 0 or aht_seconds < 0:
        raise ValueError("volume_contacts et aht_seconds doivent être >= 0.")
    return (volume_contacts * aht_seconds) / 3600


def agent_workload_hours(
    volume_contacts: float,
    aht_seconds: float,
    concurrency_factor: float = 1.0,
) -> float:
    """Charge en heures d'activité agent, après simultanéité du canal.

    Pour la voix (concurrency=1), elle est égale aux heures de traitement
    des contacts. Pour l'email/chat asynchrone, plusieurs contacts peuvent
    être actifs simultanément et la charge agent est donc inférieure à la
    charge brute des contacts.
    """
    if concurrency_factor <= 0:
        raise ValueError("concurrency_factor doit être strictement positif.")
    return workload_hours(volume_contacts, aht_seconds) / concurrency_factor


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
    if workload_hours_value < 0:
        raise ValueError("workload_hours_value doit être >= 0.")
    if available_hours_per_agent <= 0:
        raise ValueError("available_hours_per_agent doit être > 0.")
    if not 0 < occupancy_target_pct <= 100:
        raise ValueError("occupancy_target_pct doit être dans ]0,100].")
    available_capacity_hours = available_hours_per_agent * (occupancy_target_pct / 100)
    return _safe_ratio(workload_hours_value, available_capacity_hours)


def productive_hours(paid_hours_value: float, total_shrinkage_hours: float) -> float:
    """Productive Hours = Paid Hours - Total Shrinkage Hours."""
    if paid_hours_value < 0 or total_shrinkage_hours < 0:
        raise ValueError("Les heures payées et shrinkage doivent être >= 0.")
    return max(0.0, paid_hours_value - total_shrinkage_hours)


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
    return max(0.0, 100.0 - abs(forecast - actual) / abs(actual) * 100.0)


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
) -> float:
    """Effectif projeté en fin de période.

    L'attrition réduit réellement le headcount. L'absentéisme ne réduit
    jamais le headcount : il réduit la disponibilité opérationnelle et doit
    être traité séparément.
    """
    if current_hc < 0 or hiring < 0 or transfers_in < 0 or transfers_out < 0:
        raise ValueError("Les effectifs et mouvements doivent être >= 0.")
    if not 0 <= attrition_pct <= 100:
        raise ValueError("attrition_pct doit être compris entre 0 et 100%.")
    attrition_hc = min(current_hc, current_hc * attrition_pct / 100.0)
    return max(0.0, current_hc + hiring + transfers_in - transfers_out - attrition_hc)


def projected_available_headcount(
    projected_hc: float,
    absenteeism_pct: float,
) -> float:
    """HC projeté réellement disponible après absentéisme prévu."""
    if projected_hc < 0:
        raise ValueError("projected_hc doit être >= 0.")
    if not 0 <= absenteeism_pct <= 100:
        raise ValueError("absenteeism_pct doit être compris entre 0 et 100%.")
    return max(0.0, projected_hc * (1.0 - absenteeism_pct / 100.0))


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


# --- WFM control-tower metrics ------------------------------------------------

def weighted_average(values: list[float], weights: list[float]) -> float:
    """Moyenne pondérée; 0 si aucun poids exploitable."""
    if len(values) != len(weights):
        raise ValueError("values et weights doivent avoir la même longueur.")
    total_weight = sum(max(w, 0.0) for w in weights)
    if total_weight <= 0:
        return 0.0
    return sum(v * max(w, 0.0) for v, w in zip(values, weights)) / total_weight


def mean_absolute_percentage_error_pct(forecast_values: list[float], actual_values: list[float]) -> float:
    """MAPE (%) en ignorant les périodes dont l'actual est nul."""
    if len(forecast_values) != len(actual_values):
        raise ValueError("forecast_values et actual_values doivent avoir la même longueur.")
    pairs = [(f, a) for f, a in zip(forecast_values, actual_values) if a != 0]
    if not pairs:
        return 0.0
    return sum(abs(f - a) / abs(a) for f, a in pairs) / len(pairs) * 100


def weighted_absolute_percentage_error_pct(forecast_values: list[float], actual_values: list[float]) -> float:
    """WAPE (%) = somme des erreurs absolues / somme des actuals."""
    if len(forecast_values) != len(actual_values):
        raise ValueError("forecast_values et actual_values doivent avoir la même longueur.")
    actual_total = sum(abs(a) for a in actual_values)
    if actual_total <= 0:
        return 0.0
    return sum(abs(f - a) for f, a in zip(forecast_values, actual_values)) / actual_total * 100


def forecast_bias_pct(forecast_values: list[float], actual_values: list[float]) -> float:
    """Bias (%) = (Forecast - Actual) / Actual total.
    
    Positif = forecast trop haut; négatif = forecast trop bas.
    """
    if len(forecast_values) != len(actual_values):
        raise ValueError("forecast_values et actual_values doivent avoir la même longueur.")
    actual_total = sum(actual_values)
    if actual_total == 0:
        return 0.0
    return (sum(forecast_values) - actual_total) / actual_total * 100


def service_level_shortfall_pct(actual_pct: float, target_pct: float) -> float:
    """Manque de SL en points; 0 si le KPI est au-dessus de la cible."""
    return max(0.0, target_pct - actual_pct)


def coverage_pct(required_hc_hours: float, staffed_hc_hours: float) -> float:
    """Coverage = heures couvertes / heures requises, plafonnée à 100%."""
    if required_hc_hours <= 0:
        return 0.0
    covered = min(max(staffed_hc_hours, 0.0), required_hc_hours)
    return covered / required_hc_hours * 100.0


def understaffed_hours(required_hc_hours: float, staffed_hc_hours: float) -> float:
    """Heures-HC de sous-staffing, jamais négatives."""
    return max(0.0, required_hc_hours - staffed_hc_hours)


def overstaffed_hours(required_hc_hours: float, staffed_hc_hours: float) -> float:
    """Heures-HC de sur-staffing, jamais négatives."""
    return max(0.0, staffed_hc_hours - required_hc_hours)


def schedule_adherence_pct(adhered_hours: float, scheduled_hours: float) -> float:
    """Adhérence planning = temps conforme / temps planifié."""
    return _safe_ratio(adhered_hours, scheduled_hours) * 100


def staffing_adherence_proxy_pct(actual_hc_hours: float, scheduled_hc_hours: float) -> float:
    """Proxy intraday d'adhérence quand seuls des HC actuals sont disponibles.
    
    Ce n'est pas l'adhérence agent-level ACD/WFM; il compare seulement la
    couverture observée au staffing planifié.
    """
    return _safe_ratio(min(actual_hc_hours, scheduled_hc_hours), scheduled_hc_hours) * 100


def utilization_pct(workload_hours_value: float, staffed_hours: float) -> float:
    """Utilisation = charge de travail / heures staffées."""
    return _safe_ratio(workload_hours_value, staffed_hours) * 100


def schedule_efficiency_pct(required_hc_hours: float, scheduled_hc_hours: float) -> float:
    """Efficacité de planning = demande couverte / heures planifiées.
    
    Le ratio est plafonné à 100% pour ne pas récompenser un sous-staffing.
    """
    if scheduled_hc_hours <= 0:
        return 0.0
    return min(100.0, required_hc_hours / scheduled_hc_hours * 100)


def forecast_accuracy_wape_pct(forecast_values: list[float], actual_values: list[float]) -> float:
    """Accuracy dérivée du WAPE : 100 - WAPE, bornée à 0."""
    return max(0.0, 100.0 - weighted_absolute_percentage_error_pct(forecast_values, actual_values))
