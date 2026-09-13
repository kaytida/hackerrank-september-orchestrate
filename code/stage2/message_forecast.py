"""
Message-driven forecast adjustments for the 90-day balance simulation.
"""

from __future__ import annotations

from typing import Any

from stage2.message_rules import ForecastAdjustment, interpret_messages


def get_message_forecast_adjustments(
    messages: list[dict[str, str]],
    request_date: str,
) -> list[ForecastAdjustment]:
    """Return forecast-only adjustments derived from the same rules as event patches."""
    _, forecast_adjustments = interpret_messages(messages, request_date)
    return forecast_adjustments


def _is_payroll_flow(flow: dict[str, Any]) -> bool:
    """True if a projected flow represents salary or payroll income."""
    desc = (flow.get("description") or "").lower()
    category = (flow.get("category") or "").lower()
    return category == "salary" or "payroll" in desc


def apply_forecast_adjustments(
    flows: list[dict[str, Any]],
    adjustments: list[ForecastAdjustment],
    *,
    home_currency: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Apply message-driven adjustments to projected flows; return (flows, applied_count)."""
    if not adjustments:
        return flows, 0

    applied = 0
    result = list(flows)
    for adj in adjustments:
        if adj.adjustment_type == "cancel_recurring_credits":
            filtered = []
            removed = 0
            exclude_known = (adj.details or {}).get("exclude_known_future_credits")
            for flow in result:
                if flow.get("direction") != "credit":
                    filtered.append(flow)
                    continue
                if adj.category and flow.get("category") != adj.category:
                    filtered.append(flow)
                    continue
                if flow.get("source") == "recurring":
                    removed += 1
                    continue
                if exclude_known and flow.get("source") == "known_future":
                    removed += 1
                    continue
                filtered.append(flow)
            if removed:
                applied += 1
                result = filtered
            continue

        if adj.adjustment_type == "cancel_recurrence_substring":
            substrings = [
                s.lower()
                for s in (adj.details or {}).get("description_substrings", [])
            ]
            if not substrings:
                continue
            include_known = (adj.details or {}).get("include_known_future", True)
            filtered = []
            removed = 0
            for flow in result:
                source = flow.get("source")
                if source not in ("recurring", "known_future"):
                    filtered.append(flow)
                    continue
                if source == "known_future" and not include_known:
                    filtered.append(flow)
                    continue
                if adj.direction and flow.get("direction") != adj.direction:
                    filtered.append(flow)
                    continue
                if adj.category and flow.get("category") != adj.category:
                    filtered.append(flow)
                    continue
                desc = (flow.get("description") or "").lower()
                if any(sub in desc for sub in substrings):
                    removed += 1
                    continue
                filtered.append(flow)
            if removed:
                applied += 1
                result = filtered
            continue

        if adj.adjustment_type == "override_salary_from_date":
            effective = adj.flow_date
            amount = adj.amount_home
            if not effective or amount is None:
                continue
            currency = (adj.details or {}).get("currency")
            if currency and home_currency and currency.upper() != home_currency.upper():
                continue
            updated: list[dict[str, Any]] = []
            changed = 0
            for flow in result:
                if flow.get("source") != "recurring" or flow.get("direction") != "credit":
                    updated.append(flow)
                    continue
                if not _is_payroll_flow(flow):
                    updated.append(flow)
                    continue
                if flow["date"] < effective:
                    updated.append(flow)
                    continue
                copy = dict(flow)
                copy["amount_home"] = float(amount)
                copy["signed_amount"] = float(amount)
                updated.append(copy)
                changed += 1
            if changed:
                applied += 1
                result = updated
            continue

        if adj.adjustment_type == "scale_recurring_rent":
            multiplier = float((adj.details or {}).get("multiplier") or 1.0)
            if multiplier == 1.0:
                continue
            updated = []
            changed = 0
            for flow in result:
                if (
                    flow.get("source") == "recurring"
                    and flow.get("direction") == "debit"
                    and (flow.get("category") or "").lower() == "rent"
                ):
                    amt = float(flow["amount_home"]) * multiplier
                    copy = dict(flow)
                    copy["amount_home"] = amt
                    copy["signed_amount"] = -amt
                    updated.append(copy)
                    changed += 1
                else:
                    updated.append(flow)
            if changed:
                applied += 1
                result = updated
            continue

        if adj.adjustment_type == "exclude_internal_transfer_pairs":
            by_date_amount: dict[tuple[str, float], list[dict[str, Any]]] = {}
            for flow in result:
                if flow.get("source") != "known_future":
                    continue
                key = (flow["date"], round(abs(float(flow["amount_home"])), 2))
                by_date_amount.setdefault(key, []).append(flow)
            remove_ids: set[str] = set()
            for group in by_date_amount.values():
                if len(group) < 2:
                    continue
                dirs = {g.get("direction") for g in group}
                if dirs == {"credit", "debit"}:
                    for g in group:
                        eid = g.get("event_id")
                        if eid:
                            remove_ids.add(eid)
            if remove_ids:
                result = [
                    f
                    for f in result
                    if f.get("event_id") not in remove_ids
                ]
                applied += 1
            continue

        if adj.adjustment_type == "cap_invoice_payout":
            cap_date = adj.flow_date
            cap_amount = adj.amount_home
            if not cap_date or cap_amount is None:
                continue
            filtered = []
            kept_cap = False
            removed = 0
            for flow in result:
                if flow.get("direction") != "credit":
                    filtered.append(flow)
                    continue
                desc = (flow.get("description") or "").lower()
                if "invoice" not in desc and flow.get("category") not in (
                    "freelance",
                    "gig",
                    "service",
                ):
                    filtered.append(flow)
                    continue
                if flow.get("source") == "recurring":
                    removed += 1
                    continue
                if flow["date"] == cap_date and not kept_cap:
                    copy = dict(flow)
                    copy["amount_home"] = float(cap_amount)
                    copy["signed_amount"] = float(cap_amount)
                    filtered.append(copy)
                    kept_cap = True
                    continue
                if flow.get("source") == "known_future" and flow["date"] == cap_date:
                    removed += 1
                    continue
                filtered.append(flow)
            if removed or kept_cap:
                applied += 1
                result = filtered
            continue

        if adj.adjustment_type == "shift_salary_credit_dates":
            from datetime import date as date_cls
            from calendar import monthrange

            target_date = adj.flow_date
            if not target_date:
                continue
            anchor = date_cls.fromisoformat(target_date)
            updated: list[dict[str, Any]] = []
            changed = 0
            for flow in result:
                if flow.get("direction") != "credit" or not _is_payroll_flow(flow):
                    updated.append(flow)
                    continue
                flow_day = date_cls.fromisoformat(flow["date"])
                if flow_day < anchor:
                    updated.append(flow)
                    continue
                last = monthrange(flow_day.year, flow_day.month)[1]
                new_day = min(anchor.day, last)
                new_date = flow_day.replace(day=new_day)
                if new_date.isoformat() == flow["date"]:
                    updated.append(flow)
                    continue
                copy = dict(flow)
                copy["date"] = new_date.isoformat()
                updated.append(copy)
                changed += 1
            if changed:
                applied += 1
                result = updated
            continue

        if adj.adjustment_type == "use_regular_salary_only":
            updated = []
            changed = 0
            for flow in result:
                if flow.get("source") == "recurring" and _is_payroll_flow(flow):
                    desc = (flow.get("description") or "").lower()
                    if "arrears" in desc or "adjustment" in desc or "bonus" in desc:
                        changed += 1
                        continue
                updated.append(flow)
            if changed:
                applied += 1
                result = updated

    return result, applied
