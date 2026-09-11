"""Moteur Erlang C — calcul du Headcount Required (§18 du cahier des charges).

Module volontairement isolé : aucune dépendance DB ni FastAPI, uniquement
des fonctions pures et un dataclass de résultat. Formules vérifiées contre
un exemple de référence publié indépendamment (100 appels / 30 min, AHT
180s = 10 Erlangs ; 14 agents -> 88.84% de service level, ~7.8s d'ASA ; 13
agents -> 79.56%, sous la cible) — voir tests/unit/test_erlang_service.py.

Erlang B est calculé par récurrence plutôt que par la formule factorielle
classique (A^N / N!) : cette dernière déborde numériquement bien avant
d'atteindre les effectifs réels d'un centre de contacts. La récurrence est
stable à n'importe quel niveau d'effectif.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# --- Traffic Intensity -----------------------------------------------------

def traffic_intensity_erlangs(volume_contacts: float, aht_seconds: float, interval_seconds: float) -> float:
    """Intensité de trafic A = (Volume x AHT) / Durée de l'intervalle, en Erlangs.

    Un Erlang = une ligne occupée en continu sur la durée de l'intervalle.
    """
    if interval_seconds <= 0:
        raise ValueError("interval_seconds doit être strictement positif.")
    if volume_contacts < 0 or aht_seconds < 0:
        raise ValueError("volume_contacts et aht_seconds doivent être positifs ou nuls.")
    return (volume_contacts * aht_seconds) / interval_seconds


# --- Erlang B (récurrence) puis Erlang C ------------------------------------

def _erlang_b(agents: int, traffic_erlangs: float) -> float:
    """Erlang B : probabilité de blocage (tous les N serveurs occupés),
    calculée par récurrence pour éviter tout débordement factoriel.

        B(0, A) = 1
        B(n, A) = (A x B(n-1, A)) / (n + A x B(n-1, A))
    """
    b = 1.0
    for n in range(1, agents + 1):
        b = (traffic_erlangs * b) / (n + traffic_erlangs * b)
    return b


def erlang_c_probability_of_wait(agents: int, traffic_erlangs: float) -> float:
    """Erlang C : probabilité qu'un appel entrant doive attendre.

        C(N, A) = (N x B(N, A)) / (N - A x (1 - B(N, A)))

    Système instable (agents <= trafic) : renvoie 1.0 (attente certaine, la
    file grandit sans limite).
    """
    if agents <= 0 or agents <= traffic_erlangs:
        return 1.0
    b = _erlang_b(agents, traffic_erlangs)
    return (agents * b) / (agents - traffic_erlangs * (1 - b))


def service_level_erlang_c(
    agents: int,
    traffic_erlangs: float,
    aht_seconds: float,
    answer_time_target_seconds: float,
) -> float:
    """Service Level (%) attendu avec ce nombre d'agents (formule d'Erlang C).

        SL(N) = 1 - C(N, A) x e^(-(N - A) x T / AHT)
    """
    if agents <= 0 or agents <= traffic_erlangs:
        return 0.0
    c = erlang_c_probability_of_wait(agents, traffic_erlangs)
    exponent = -(agents - traffic_erlangs) * (answer_time_target_seconds / aht_seconds)
    return (1 - c * math.exp(exponent)) * 100


def average_speed_of_answer_erlang_c(agents: int, traffic_erlangs: float, aht_seconds: float) -> float:
    """ASA (secondes) attendue avec ce nombre d'agents.

        ASA = C(N, A) x AHT / (N - A)

    Système instable : renvoie math.inf (temps d'attente non borné).
    """
    if agents <= 0 or agents <= traffic_erlangs:
        return math.inf
    c = erlang_c_probability_of_wait(agents, traffic_erlangs)
    return (c * aht_seconds) / (agents - traffic_erlangs)


def occupancy_from_traffic_pct(traffic_erlangs: float, agents: int) -> float:
    """Occupancy (%) = Trafic / Agents x 100."""
    if agents <= 0:
        return 0.0
    return (traffic_erlangs / agents) * 100


# --- Required HC -------------------------------------------------------------

@dataclass(frozen=True)
class RequiredAgentsResult:
    """Résultat du dimensionnement : trafic, HC net requis, et les niveaux
    de service/occupancy réellement atteints avec ce HC (jamais supposés
    exacts au dixième — Erlang C progresse par paliers entiers d'agents)."""

    traffic_erlangs: float
    net_required_hc: int
    achieved_service_level_pct: float
    achieved_occupancy_pct: float
    achieved_asa_seconds: float


def find_required_agents(
    volume_contacts: float,
    aht_seconds: float,
    interval_seconds: float,
    service_level_target_pct: float,
    answer_time_target_seconds: float,
    occupancy_target_pct: Optional[float] = None,
    max_agents: int = 2000,
) -> RequiredAgentsResult:
    """Nombre minimal d'agents (Net Required HC) satisfaisant à la fois :
      - le Service Level cible (§14) ;
      - la contrainte d'Occupancy maximale, si fournie (§17 — au-delà,
        l'AHT réel dérive et les agents s'épuisent, cf. §18).

    Incrémente les agents un par un à partir du minimum stable (N > A) —
    Erlang C n'a pas de solution analytique directe pour N, cette recherche
    itérative est l'approche standard de l'industrie.
    """
    traffic = traffic_intensity_erlangs(volume_contacts, aht_seconds, interval_seconds)

    if traffic <= 0:
        return RequiredAgentsResult(
            traffic_erlangs=traffic,
            net_required_hc=0,
            achieved_service_level_pct=100.0,
            achieved_occupancy_pct=0.0,
            achieved_asa_seconds=0.0,
        )

    agents = math.floor(traffic) + 1
    while agents <= max_agents:
        sl = service_level_erlang_c(agents, traffic, aht_seconds, answer_time_target_seconds)
        occupancy = occupancy_from_traffic_pct(traffic, agents)

        sl_ok = sl >= service_level_target_pct
        occupancy_ok = occupancy_target_pct is None or occupancy <= occupancy_target_pct

        if sl_ok and occupancy_ok:
            return RequiredAgentsResult(
                traffic_erlangs=traffic,
                net_required_hc=agents,
                achieved_service_level_pct=sl,
                achieved_occupancy_pct=occupancy,
                achieved_asa_seconds=average_speed_of_answer_erlang_c(agents, traffic, aht_seconds),
            )
        agents += 1

    raise RuntimeError(
        f"Aucun effectif <= {max_agents} agents ne satisfait les cibles "
        f"(trafic={traffic:.2f} Erlangs, SL cible={service_level_target_pct}%, "
        f"occupancy cible={occupancy_target_pct}%)."
    )


# --- Application du Shrinkage : Net -> Gross Required HC ----------------------

def apply_shrinkage(net_required_hc: float, shrinkage_pct: float) -> float:
    """Gross Required HC = Net Required HC / (1 - shrinkage%) (§18).

    Le Net Required HC est le nombre d'agents effectivement au téléphone ;
    le Gross ajoute la marge nécessaire pour couvrir pauses, absences,
    formations, etc. (voir app/services/shrinkage_service.py, commit 10).
    """
    if not 0 <= shrinkage_pct < 100:
        raise ValueError("shrinkage_pct doit être compris entre 0 (inclus) et 100 (exclu).")
    return net_required_hc / (1 - shrinkage_pct / 100)
