"""Planning automatique de mix de shifts, en mode simulation.

Le moteur ne touche jamais à la base. Il cherche gloutonnement un ensemble
de gabarits de shifts qui réduit les heures de sous-staffing tout en limitant
le sur-staffing. L'utilisateur garde ensuite la décision d'affectation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Iterable

from app.models.intraday import IntervalForecast
from app.models.shift import Shift
from app.services import intraday_service, scheduling_service


@dataclass(frozen=True)
class ShiftRecommendation:
    shift_id: int | None
    shift_name: str
    headcount: int
    start_time: time
    end_time: time
    shortage_hours_after: float
    surplus_hours_after: float


def _generate_activities(shift: Shift) -> tuple[time | None, time | None, time | None, time | None, time | None, time | None]:
    elapsed_minutes = int(round(
        __import__("app.services.workforce_service", fromlist=["shift_elapsed_hours"]).shift_elapsed_hours(shift) * 60
    ))
    if elapsed_minutes <= 0:
        return (None, None, None, None, None, None)
    start_minutes = shift.start_time.hour * 60 + shift.start_time.minute

    def at(offset: int) -> time:
        minute = (start_minutes + offset) % (24 * 60)
        return time(minute // 60, minute % 60)

    def pair(offset: int, duration: int) -> tuple[time, time]:
        return at(offset), at(offset + duration)

    break_len = max(shift.break_minutes, 0)
    lunch_len = max(shift.lunch_minutes, 0)
    b1_offset = max(75, int(elapsed_minutes * 0.27))
    lunch_offset = int(elapsed_minutes * 0.50)
    b2_offset = int(elapsed_minutes * 0.76)
    b1 = pair(b1_offset, break_len) if shift.break_count >= 1 and break_len else (None, None)
    b2 = pair(b2_offset, break_len) if shift.break_count >= 2 and break_len else (None, None)
    lunch = pair(lunch_offset, lunch_len) if lunch_len else (None, None)
    return b1[0], b1[1], b2[0], b2[1], lunch[0], lunch[1]


def _shift_covers(shift: Shift, start: time, end: time | None = None) -> bool:
    if not (
        shift.start_time <= end if end is not None and shift.start_time <= shift.end_time
        else True
    ):
        pass
    if shift.start_time <= shift.end_time:
        covered = shift.start_time <= start < shift.end_time
    else:
        covered = start >= shift.start_time or start < shift.end_time
    if not covered:
        return False
    if end is None:
        return True
    b1s, b1e, b2s, b2e, ls, le = _generate_activities(shift)
    return not any(
        scheduling_service._overlaps(bs, be, start, end)
        for bs, be in ((b1s, b1e), (b2s, b2e), (ls, le))
    )


def _score_candidate(required: list[float], current: list[float], cover: list[bool]) -> float:
    shortage_before = sum(max(r - c, 0.0) for r, c in zip(required, current))
    simulated = [c + (1.0 if x else 0.0) for c, x in zip(current, cover)]
    shortage_after = sum(max(r - c, 0.0) for r, c in zip(required, simulated))
    surplus_penalty = sum(max(c - r, 0.0) for r, c in zip(required, simulated))
    return (shortage_before - shortage_after) - 0.15 * surplus_penalty


def recommend_shift_mix(
    intervals: list[IntervalForecast],
    shifts: Iterable[Shift],
    *,
    max_agents: int,
) -> list[ShiftRecommendation]:
    """Propose un mix de shifts pour réduire le sous-staffing.

    max_agents borne le nombre d'agents ajoutables dans la simulation.
    Les shifts sans id (rare, tests unitaires) restent utilisables.
    """
    if not intervals or max_agents <= 0:
        return []

    shifts = [s for s in shifts if s.is_active]
    if not shifts:
        return []

    starts = [i.interval_start for i in intervals]
    required = [max(i.required_hc - i.scheduled_hc, 0.0) for i in intervals]
    current = [0.0 for _ in intervals]
    selected: dict[int | None, ShiftRecommendation] = {}

    for _ in range(max_agents):
        candidates = []
        for shift in shifts:
            cover = [_shift_covers(shift, i.interval_start, i.interval_end) for i in intervals]
            score = _score_candidate(required, current, cover)
            candidates.append((score, shift, cover))
        score, shift, cover = max(candidates, key=lambda x: x[0])
        if score <= 0:
            break
        current = [c + (1.0 if x else 0.0) for c, x in zip(current, cover)]
        key = shift.id
        prev = selected.get(key)
        selected[key] = ShiftRecommendation(
            shift_id=key,
            shift_name=shift.name,
            headcount=(prev.headcount + 1) if prev else 1,
            start_time=shift.start_time,
            end_time=shift.end_time,
            shortage_hours_after=0.0,
            surplus_hours_after=0.0,
        )

    interval_hours = [intraday_service.interval_duration_hours(i.interval_start, i.interval_end) for i in intervals]
    shortage_after = sum(max(r - c, 0.0) * h for r, c, h in zip(required, current, interval_hours))
    surplus_after = sum(max(c - r, 0.0) * h for r, c, h in zip(required, current, interval_hours))
    return [
        ShiftRecommendation(
            shift_id=item.shift_id,
            shift_name=item.shift_name,
            headcount=item.headcount,
            start_time=item.start_time,
            end_time=item.end_time,
            shortage_hours_after=shortage_after,
            surplus_hours_after=surplus_after,
        )
        for item in selected.values()
    ]
