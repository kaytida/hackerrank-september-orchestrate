from __future__ import annotations

import calendar
import statistics
from datetime import date, timedelta

from config import (
    HIGH_NOISE_VARIABLE_CATEGORIES,
    RECURRENCE_MIN_OCCURRENCES,
    RECURRENCE_MIN_OCCURRENCES_VARIABLE,
    VARIABLE_SPEND_CATEGORIES,
    VARIABLE_WEEKLY_MIN_GAP_DAYS,
)
from stage2.models import ResolvedCashEvent


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def recurrence_key(event: ResolvedCashEvent) -> str:
    description = (event.description or "").strip().lower()
    return "|".join(
        [
            event.category.strip().lower(),
            event.event_type.strip().lower(),
            description,
        ]
    )


def _classify_interval(median_days: float) -> str | None:
    if 5 <= median_days <= 9:
        return "weekly"
    if 12 <= median_days <= 17:
        return "biweekly"
    if 20 <= median_days <= 38:
        return "monthly"
    return None


def _is_variable_category(category: str) -> bool:
    return category.strip().lower() in VARIABLE_SPEND_CATEGORIES


def _is_high_noise_variable(category: str) -> bool:
    return category.strip().lower() in HIGH_NOISE_VARIABLE_CATEGORIES


def add_calendar_month(value: date) -> date:
    """Advance by one calendar month, clamping the day when needed (e.g. Jan 31 -> Feb 28)."""
    year = value.year
    month = value.month + 1
    if month > 12:
        month = 1
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))


def advance_recurrence_date(current: date, series: dict[str, object]) -> date:
    interval = str(series.get("interval") or "")
    if interval == "monthly":
        return add_calendar_month(current)
    step_days = int(series.get("projection_gap_days") or round(float(series["median_gap_days"])))
    return current + timedelta(days=step_days)


def _project_amount(
    events: list[ResolvedCashEvent],
    protected_categories: frozenset[str] | None = None,
) -> float:
    _ = protected_categories
    amounts = [e.amount_home for e in events]
    category = events[-1].category
    if _is_variable_category(category):
        return float(statistics.median(amounts))
    flex = events[-1].flexibility
    if flex == "reducible":
        recent = amounts[-3:] if len(amounts) >= 3 else amounts
        return float(max(recent))
    if flex == "stoppable":
        recent = amounts[-3:] if len(amounts) >= 3 else amounts
        return float(statistics.median(recent))
    if len(amounts) >= 3:
        return float(statistics.median(amounts[-3:]))
    return float(statistics.median(amounts))


def detect_recurrence_series(
    historical: list[ResolvedCashEvent],
    protected_categories: frozenset[str] | None = None,
) -> list[dict[str, object]]:
    """Detect recurring patterns from settled history before request_date."""
    groups: dict[str, list[ResolvedCashEvent]] = {}
    for event in historical:
        groups.setdefault(recurrence_key(event), []).append(event)

    series: list[dict[str, object]] = []
    for key, events in groups.items():
        events = sorted(events, key=lambda e: e.settlement_date)
        category = events[-1].category
        min_occ = (
            RECURRENCE_MIN_OCCURRENCES_VARIABLE
            if _is_variable_category(category)
            else RECURRENCE_MIN_OCCURRENCES
        )
        if len(events) < min_occ:
            continue
        last_desc = (events[-1].description or "").lower()
        if events[-1].direction == "credit" and (
            "final employer" in last_desc
            or "final payroll" in last_desc
            or last_desc.startswith("final ")
        ):
            continue
        gaps = []
        for prev, curr in zip(events, events[1:]):
            gap = (_parse_date(curr.settlement_date) - _parse_date(prev.settlement_date)).days
            if gap > 0:
                gaps.append(gap)
        if not gaps:
            continue
        median_gap = float(statistics.median(gaps))
        interval = _classify_interval(median_gap)
        if interval is None:
            continue
        if _is_high_noise_variable(category) and interval != "monthly":
            continue
        if (
            _is_variable_category(category)
            and not _is_high_noise_variable(category)
            and interval in ("weekly", "biweekly")
        ):
            pass
        elif _is_variable_category(category) and interval != "monthly":
            continue
        sample = events[-1]
        median_gap_int = int(round(median_gap))
        projection_gap_days = median_gap_int
        if (
            _is_variable_category(category)
            and not _is_high_noise_variable(category)
            and interval in ("weekly", "biweekly")
        ):
            projection_gap_days = max(median_gap_int, VARIABLE_WEEKLY_MIN_GAP_DAYS)
        amount_home = _project_amount(events, protected_categories)
        series.append(
            {
                "recurrence_key": key,
                "interval": interval,
                "median_gap_days": median_gap,
                "projection_gap_days": projection_gap_days,
                "direction": sample.direction,
                "category": sample.category,
                "event_type": sample.event_type,
                "description": sample.description,
                "amount_home": amount_home,
                "last_settlement_date": events[-1].settlement_date,
                "occurrence_count": len(events),
            }
        )
    return series
