"""Conservative supplemental projections for protected variable expense categories."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from config import VARIABLE_SPEND_CATEGORIES
from stage2.models import ResolvedCashEvent
from stage2.recurrence import add_calendar_month


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _month_key(d: date) -> tuple[int, int]:
    return (d.year, d.month)


def _max_monthly_category_spend(
    cash_events: list[ResolvedCashEvent],
    category: str,
    request_date: date,
) -> float:
    totals: dict[tuple[int, int], float] = {}
    for event in cash_events:
        if event.status != "settled" or event.direction != "debit":
            continue
        if event.category.strip().lower() != category:
            continue
        settlement = _parse_date(event.settlement_date)
        if settlement >= request_date:
            continue
        totals[_month_key(settlement)] = totals.get(_month_key(settlement), 0.0) + float(
            event.amount_home
        )
    if not totals:
        return 0.0
    return max(totals.values())


def _category_debits_in_month(
    flows: list[dict[str, Any]],
    category: str,
    year: int,
    month: int,
) -> float:
    total = 0.0
    for flow in flows:
        if flow.get("direction") != "debit":
            continue
        if (flow.get("category") or "").strip().lower() != category:
            continue
        flow_date = _parse_date(flow["date"])
        if flow_date.year == year and flow_date.month == month:
            total += abs(float(flow.get("amount_home", 0)))
    return total


def supplement_protected_variable_spend(
    flows: list[dict[str, Any]],
    cash_events: list[ResolvedCashEvent],
    request_date: date,
    horizon_end: date,
    protected_categories: frozenset[str],
) -> list[dict[str, Any]]:
    """
    Ensure each protected variable category meets at least the historical
    peak calendar-month spend (conservative essential budgeting).
    """
    result = list(flows)
    variable_protected = {
        c.strip().lower()
        for c in protected_categories
        if c.strip().lower() in VARIABLE_SPEND_CATEGORIES
    }
    if not variable_protected:
        return result

    current_month = date(request_date.year, request_date.month, 1)
    end_month = date(horizon_end.year, horizon_end.month, 1)
    month_cursor = current_month

    while month_cursor <= end_month:
        year, month = month_cursor.year, month_cursor.month
        last_day = monthrange(year, month)[1]
        supplement_day = min(max(request_date.day, 15), last_day)
        if month_cursor == current_month and request_date.day > supplement_day:
            supplement_day = min(request_date.day, last_day)
        flow_date = date(year, month, supplement_day)
        if flow_date < request_date or flow_date > horizon_end:
            month_cursor = add_calendar_month(month_cursor)
            continue

        for category in sorted(variable_protected):
            target = _max_monthly_category_spend(cash_events, category, request_date)
            if target <= 0:
                continue
            already = _category_debits_in_month(result, category, year, month)
            shortfall = target - already
            # Only top up when recurrence left a material gap (avoid double-counting).
            if shortfall <= max(50.0, target * 0.15):
                continue
            result.append(
                {
                    "date": flow_date.isoformat(),
                    "signed_amount": -shortfall,
                    "direction": "debit",
                    "amount_home": shortfall,
                    "source": "protected_category_floor",
                    "recurrence_key": f"protected_floor|{category}",
                    "event_id": None,
                    "category": category,
                    "description": f"Protected {category} monthly floor",
                    "status": "projected",
                }
            )
        month_cursor = add_calendar_month(month_cursor)

    return result
