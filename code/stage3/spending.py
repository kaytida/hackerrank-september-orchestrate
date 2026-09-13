"""Spending change strings applied to projected flows during planning."""

from __future__ import annotations

from typing import Any

from stage2.models import ResolvedCashEvent
from stage2.recurrence import recurrence_key


def _event_by_id(cash_events: list[ResolvedCashEvent], event_id: str) -> ResolvedCashEvent | None:
    """Find a resolved event by event_id."""
    for event in cash_events:
        if event.event_id == event_id:
            return event
    return None


def apply_spending_changes(
    baseline_flows: list[dict[str, Any]],
    cash_events: list[ResolvedCashEvent],
    spending_changes: str,
) -> list[dict[str, Any]]:
    """Apply stop:/reduce_to: tokens to recurring projected flows."""
    if not spending_changes or spending_changes == "none":
        return list(baseline_flows)

    flows = list(baseline_flows)
    for part in spending_changes.split("|"):
        part = part.strip()
        if not part:
            continue
        if part.startswith("stop:"):
            event_id = part.split(":", 1)[1]
            event = _event_by_id(cash_events, event_id)
            if not event:
                continue
            key = recurrence_key(event)
            flows = [
                f
                for f in flows
                if not (f.get("source") == "recurring" and f.get("recurrence_key") == key)
            ]
        elif part.startswith("reduce_to:"):
            _, rest = part.split(":", 1)
            event_id, new_amount_str = rest.rsplit(":", 1)
            event = _event_by_id(cash_events, event_id)
            if not event:
                continue
            key = recurrence_key(event)
            new_amount = float(new_amount_str)
            updated: list[dict[str, Any]] = []
            for flow in flows:
                if flow.get("source") == "recurring" and flow.get("recurrence_key") == key:
                    direction = flow.get("direction", "debit")
                    signed = new_amount if direction == "credit" else -new_amount
                    copy = dict(flow)
                    copy["amount_home"] = new_amount
                    copy["signed_amount"] = signed
                    updated.append(copy)
                else:
                    updated.append(flow)
            flows = updated
    return flows


def enumerate_spending_candidates(
    cash_events: list[ResolvedCashEvent],
    stoppable_categories: list[str],
    reducible_categories: list[str],
) -> list[str]:
    """Generate spending change strings to try (none handled separately)."""
    candidates: list[str] = []
    seen_stop: set[str] = set()
    for event in cash_events:
        if event.flexibility == "stoppable" and event.category in stoppable_categories:
            if event.event_id not in seen_stop:
                candidates.append(f"stop:{event.event_id}")
                seen_stop.add(event.event_id)

    reduce_options: list[tuple[float, str]] = []
    seen_reduce_keys: set[str] = set()
    for event in cash_events:
        if event.flexibility != "reducible":
            continue
        if event.category not in reducible_categories:
            continue
        if event.minimum_allowed_amount is None:
            continue
        key = recurrence_key(event)
        if key in seen_reduce_keys:
            continue
        seen_reduce_keys.add(key)
        savings = event.amount_home - float(event.minimum_allowed_amount)
        reduce_options.append(
            (savings, f"reduce_to:{event.event_id}:{event.minimum_allowed_amount}")
        )
    reduce_options.sort(key=lambda item: item[0], reverse=True)
    candidates.extend(option for _, option in reduce_options)
    return candidates
