from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from config import FORECAST_HORIZON_DAYS
from stage2.image_amounts import image_evidence_for_request
from stage2.message_forecast import (
    ForecastAdjustment,
    apply_forecast_adjustments,
    get_message_forecast_adjustments,
)
from stage2.models import ResolvedCashEvent, ResolvedLedger
from stage2.recurrence import advance_recurrence_date, detect_recurrence_series, recurrence_key


def _parse_date(value: str) -> date:
    """Parse ISO date strings used in forecast flow dicts."""
    return date.fromisoformat(value)


def _format_date(value: date) -> str:
    """Format a date as ISO string for projected flow keys."""
    return value.isoformat()


def _signed_amount(event: ResolvedCashEvent) -> float:
    """Return +amount_home for credits and -amount_home for debits."""
    if event.direction == "credit":
        return event.amount_home
    return -event.amount_home


def _is_known_future(event: ResolvedCashEvent, request_date: date) -> bool:
    """Include scheduled cash flows; pending debits only (problem_statement: ignore pending credits)."""
    settlement = _parse_date(event.settlement_date)
    if settlement < request_date:
        return False
    status = event.status
    if status == "scheduled":
        return True
    if status == "pending" and event.direction == "debit":
        return True
    return False


def _collect_known_future_flows(
    cash_events: list[ResolvedCashEvent],
    request_date: date,
    horizon_end: date,
) -> list[dict[str, Any]]:
    """Build flow dicts for scheduled/pending-debit events within the forecast window."""
    flows: list[dict[str, Any]] = []
    for event in cash_events:
        if not _is_known_future(event, request_date):
            continue
        settlement = _parse_date(event.settlement_date)
        if settlement > horizon_end:
            continue
        flows.append(
            {
                "date": event.settlement_date,
                "signed_amount": _signed_amount(event),
                "direction": event.direction,
                "amount_home": event.amount_home,
                "source": "known_future",
                "recurrence_key": recurrence_key(event),
                "event_id": event.event_id,
                "category": event.category,
                "description": event.description,
                "status": event.status,
            }
        )
    return flows


def _salary_ended_before_request(
    cash_events: list[ResolvedCashEvent],
    request_date: date,
) -> bool:
    """True when the latest settled salary credit before request_date is a final payroll."""
    latest: ResolvedCashEvent | None = None
    for event in cash_events:
        if event.status != "settled":
            continue
        if event.direction != "credit" or event.category != "salary":
            continue
        settlement = _parse_date(event.settlement_date)
        if settlement >= request_date:
            continue
        if latest is None or settlement > _parse_date(latest.settlement_date):
            latest = event
    if latest is None:
        return False
    desc = (latest.description or "").lower()
    return "final" in desc


def _collect_recurrence_flows(
    cash_events: list[ResolvedCashEvent],
    request_date: date,
    horizon_end: date,
    occupied: set[tuple[str, str]],
    protected_categories: frozenset[str] | None = None,
    category_occupied: set[tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Project recurring series forward, avoiding slots already taken by known flows."""
    historical = [
        e
        for e in cash_events
        if e.status == "settled" and _parse_date(e.settlement_date) < request_date
    ]
    series_list = detect_recurrence_series(historical, protected_categories)
    flows: list[dict[str, Any]] = []
    category_slots = category_occupied or set()
    salary_ended = _salary_ended_before_request(cash_events, request_date)

    for series in series_list:
        if (
            salary_ended
            and str(series.get("direction")) == "credit"
            and str(series.get("category")) == "salary"
        ):
            continue
        key = str(series["recurrence_key"])
        last_date = _parse_date(str(series["last_settlement_date"]))
        amount = float(series["amount_home"])
        direction = str(series["direction"])
        signed = amount if direction == "credit" else -amount
        next_date = advance_recurrence_date(last_date, series)
        while next_date <= horizon_end:
            while next_date < request_date:
                next_date = advance_recurrence_date(next_date, series)
            if next_date > horizon_end:
                break
            flow_date = next_date
            date_str = _format_date(flow_date)
            slot = (key, date_str)
            category_slot = (
                str(series["category"]).strip().lower(),
                direction,
                date_str,
            )
            if slot not in occupied and category_slot not in category_slots:
                flows.append(
                    {
                        "date": date_str,
                        "signed_amount": signed,
                        "direction": direction,
                        "amount_home": amount,
                        "source": "recurring",
                        "recurrence_key": key,
                        "event_id": None,
                        "category": str(series["category"]),
                        "description": str(series["description"]),
                        "status": "projected",
                    }
                )
            next_date = advance_recurrence_date(flow_date, series)
    return flows


def _simulate_daily_balances(
    request_date: date,
    horizon_end: date,
    starting_balance: float,
    minimum_balance: float,
    flows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Walk day-by-day applying debits then credits; record end-of-day balance."""
    by_date: dict[str, list[dict[str, Any]]] = {}
    for flow in flows:
        by_date.setdefault(flow["date"], []).append(flow)

    daily: list[dict[str, Any]] = []
    balance = starting_balance
    current = request_date
    while current <= horizon_end:
        date_str = _format_date(current)
        day_flows = by_date.get(date_str, [])
        debits = [f for f in day_flows if f["signed_amount"] < 0]
        credits = [f for f in day_flows if f["signed_amount"] > 0]
        start_balance = balance
        for flow in debits + credits:
            balance += float(flow["signed_amount"])
        daily.append(
            {
                "date": date_str,
                "balance_start": round(start_balance, 2),
                "balance_end": round(balance, 2),
                "minimum_balance_required": minimum_balance,
                "below_minimum": balance < minimum_balance,
                "flow_count": len(day_flows),
            }
        )
        current += timedelta(days=1)
    return daily


def is_balance_safe(
    request_date: str,
    starting_balance: float,
    minimum_balance: float,
    baseline_flows: list[dict[str, Any]],
    extra_payment_flows: list[dict[str, Any]] | None = None,
) -> bool:
    """Return True if end-of-day balances stay at or above minimum through the horizon."""
    start = _parse_date(request_date)
    horizon_end = start + timedelta(days=FORECAST_HORIZON_DAYS)
    merged = list(baseline_flows)
    if extra_payment_flows:
        merged = merged + extra_payment_flows
    daily = _simulate_daily_balances(
        start, horizon_end, starting_balance, minimum_balance, merged
    )
    return all(not day["below_minimum"] for day in daily)


def payment_flows(plan: list[tuple[str, float]]) -> list[dict[str, Any]]:
    """Convert (date, amount) payment plan tuples into forecast debit flow dicts."""
    flows: list[dict[str, Any]] = []
    for pay_date, amount in plan:
        if amount <= 0:
            continue
        flows.append(
            {
                "date": pay_date,
                "signed_amount": -float(amount),
                "direction": "debit",
                "amount_home": float(amount),
                "source": "request_payment",
                "recurrence_key": None,
                "event_id": None,
                "category": "request",
                "description": "Request payment",
                "status": "planned",
            }
        )
    return flows


def _image_salary_adjustments(
    request_id: str,
    request_date: str,
) -> list[ForecastAdjustment]:
    """Use hand-extracted payslip amounts from temp_data/images.json (no vision LLM)."""
    adjustments: list[ForecastAdjustment] = []
    for index, image in enumerate(image_evidence_for_request(request_id)):
        amount_raw = (image.get("resolved_amount") or "").strip()
        if not amount_raw:
            continue
        document_type = (image.get("document_type") or "").lower()
        summary = (image.get("summary") or "").lower()
        if "payslip" not in document_type and "pay slip" not in summary and "salary" not in summary:
            continue
        try:
            amount = float(amount_raw.replace(",", ""))
        except ValueError:
            continue
        adjustments.append(
            ForecastAdjustment(
                adjustment_id=f"image_{index}_salary_net",
                adjustment_type="override_salary_from_date",
                recurrence_key=None,
                event_id=None,
                flow_date=request_date,
                amount_home=amount,
                direction="credit",
                category="salary",
                details={"source": "images_json"},
            )
        )
    return adjustments


def build_ninety_day_forecast(
    ledger: ResolvedLedger,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Build baseline 90-day balance forecast from request_date (no request payments).

    Applies deterministic message and image salary adjustments to projected flows.
    """
    request_date = _parse_date(ledger.request_date)
    horizon_end = request_date + timedelta(days=FORECAST_HORIZON_DAYS)

    known_flows = _collect_known_future_flows(
        ledger.cash_events, request_date, horizon_end
    )
    occupied = {
        (f["recurrence_key"], f["date"])
        for f in known_flows
        if f.get("recurrence_key")
    }
    category_occupied = {
        (
            str(f.get("category", "")).strip().lower(),
            str(f.get("direction", "")).strip().lower(),
            f["date"],
        )
        for f in known_flows
    }
    protect_raw = (ledger.metadata or {}).get("expense_categories_to_protect") or []
    protected = frozenset(c.strip().lower() for c in protect_raw if str(c).strip())
    recurring_flows = _collect_recurrence_flows(
        ledger.cash_events,
        request_date,
        horizon_end,
        occupied,
        protected,
        category_occupied,
    )

    projected_flows = known_flows + recurring_flows
    projected_flows.sort(key=lambda f: (f["date"], f["source"], f.get("event_id") or ""))

    adjustments = get_message_forecast_adjustments(messages, ledger.request_date)
    adjustments = adjustments + _image_salary_adjustments(
        ledger.request_id, ledger.request_date
    )
    projected_flows, adjustment_count = apply_forecast_adjustments(
        projected_flows,
        adjustments,
        home_currency=ledger.home_currency,
    )
    daily_balances = _simulate_daily_balances(
        request_date,
        horizon_end,
        ledger.starting_balance_home,
        ledger.minimum_balance_to_keep,
        projected_flows,
    )

    min_balance_seen = min(d["balance_end"] for d in daily_balances)
    days_below_minimum = sum(1 for d in daily_balances if d["below_minimum"])
    first_below: dict[str, Any] | None = None
    for day in daily_balances:
        if day["below_minimum"]:
            day_flows = [f for f in projected_flows if f["date"] == day["date"]]
            first_below = {
                "date": day["date"],
                "balance_end": day["balance_end"],
                "minimum_balance_required": day["minimum_balance_required"],
                "flow_count": day["flow_count"],
                "flows": [
                    {
                        "source": f.get("source"),
                        "signed_amount": f.get("signed_amount"),
                        "category": f.get("category"),
                        "description": (f.get("description") or "")[:80],
                    }
                    for f in day_flows
                ],
            }
            break

    return {
        "forecast_start_date": ledger.request_date,
        "forecast_end_date": _format_date(horizon_end),
        "horizon_days": FORECAST_HORIZON_DAYS,
        "starting_balance_home": ledger.starting_balance_home,
        "minimum_balance_to_keep": ledger.minimum_balance_to_keep,
        "message_forecast_adjustment_count": adjustment_count,
        "message_forecast_stub": adjustment_count == 0 and not adjustments,
        "projected_flow_count": len(projected_flows),
        "known_future_flow_count": len(known_flows),
        "recurring_flow_count": len(recurring_flows),
        "min_balance_end_of_day": round(min_balance_seen, 2),
        "days_below_minimum": days_below_minimum,
        "first_below_minimum": first_below,
        "projected_flows": projected_flows,
        "daily_balances": daily_balances,
    }
