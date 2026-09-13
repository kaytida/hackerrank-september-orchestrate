"""Filter financial events into home-currency cash ledger rows."""

from __future__ import annotations

from datetime import date

from stage2.fx import ExchangeRateTable
from stage2.models import ExcludedEvent, ResolvedCashEvent


def _parse_date(value: str) -> date:
    """Parse ISO date strings from event fields."""
    return date.fromisoformat(value)


def _superseded_by_linked_event(resolved: list[ResolvedCashEvent]) -> set[str]:
    """Drop earlier lifecycle rows when a later linked event replaces them."""
    by_id = {event.event_id: event for event in resolved}
    superseded: set[str] = set()
    for event in resolved:
        parent_id = (event.linked_event_id or "").strip()
        if not parent_id or parent_id not in by_id:
            continue
        parent = by_id[parent_id]
        try:
            child_date = _parse_date(event.settlement_date)
            parent_date = _parse_date(parent.settlement_date)
        except ValueError:
            continue
        if child_date < parent_date:
            continue
        if event.status in ("settled", "cancelled", "failed"):
            superseded.add(parent_id)
    return superseded


def _should_exclude(event: dict[str, str]) -> str | None:
    """Return an exclusion reason code, or None if the event may enter the cash ledger."""
    status = (event.get("status") or "").strip().lower()
    direction = (event.get("direction") or "").strip().lower()
    event_type = (event.get("event_type") or "").strip().lower()

    if status == "unrealized" or event_type == "investment_valuation":
        return "unrealized_investment"
    if direction == "non_cash":
        return "non_cash"
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "cancelled"
    if status == "pending" and direction == "credit":
        return "pending_credit"
    return None


def _settlement_date(event: dict[str, str]) -> str:
    """Prefer settlement_date, falling back to event_date."""
    settlement = (event.get("settlement_date") or "").strip()
    if settlement:
        return settlement
    return (event.get("event_date") or "").strip()


def resolve_cash_events(
    events: list[dict[str, str]],
    home_currency: str,
    fx: ExchangeRateTable,
) -> tuple[list[ResolvedCashEvent], list[ExcludedEvent]]:
    """Filter, convert to home currency, and drop superseded events."""
    resolved: list[ResolvedCashEvent] = []
    excluded: list[ExcludedEvent] = []

    for event in events:
        event_id = event["event_id"]
        reason = _should_exclude(event)
        if reason:
            excluded.append(ExcludedEvent(event_id=event_id, reason=reason))
            continue

        amount_raw = (event.get("amount") or "").strip()
        if not amount_raw:
            excluded.append(ExcludedEvent(event_id=event_id, reason="missing_amount"))
            continue

        currency = (event.get("currency") or home_currency).strip()
        try:
            original_amount = float(amount_raw)
        except ValueError:
            excluded.append(ExcludedEvent(event_id=event_id, reason="invalid_amount"))
            continue

        settlement_date = _settlement_date(event)
        if not settlement_date:
            excluded.append(ExcludedEvent(event_id=event_id, reason="missing_settlement_date"))
            continue

        try:
            amount_home = fx.convert(original_amount, currency, home_currency, settlement_date)
        except ValueError:
            excluded.append(
                ExcludedEvent(event_id=event_id, reason=f"fx_unavailable_{currency}_to_{home_currency}")
            )
            continue

        min_allowed_raw = (event.get("minimum_allowed_amount") or "").strip()
        minimum_allowed = float(min_allowed_raw) if min_allowed_raw else None

        resolved.append(
            ResolvedCashEvent(
                event_id=event_id,
                settlement_date=settlement_date,
                event_date=(event.get("event_date") or "").strip(),
                direction=(event.get("direction") or "").strip().lower(),
                category=(event.get("category") or "").strip(),
                event_type=(event.get("event_type") or "").strip(),
                description=(event.get("description") or "").strip(),
                status=(event.get("status") or "").strip().lower(),
                flexibility=(event.get("flexibility") or "").strip(),
                minimum_allowed_amount=minimum_allowed,
                original_currency=currency,
                original_amount=original_amount,
                amount_home=amount_home,
                home_currency=home_currency,
                linked_event_id=(event.get("linked_event_id") or "").strip(),
                amount_source=(event.get("_amount_source") or "csv"),
            )
        )

    superseded = _superseded_by_linked_event(resolved)
    if superseded:
        for event_id in sorted(superseded):
            excluded.append(ExcludedEvent(event_id=event_id, reason="superseded_by_linked_event"))
        resolved = [e for e in resolved if e.event_id not in superseded]

    resolved.sort(key=lambda e: (e.settlement_date, e.event_id))
    return resolved, excluded
