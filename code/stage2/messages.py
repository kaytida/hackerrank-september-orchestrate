"""Message-derived patches to financial events before ledger resolution."""

from __future__ import annotations

from datetime import date

from stage2.message_rules import EventPatch, interpret_messages


def _parse_date(value: str) -> date:
    """Parse request_date for comparing event settlement dates."""
    return date.fromisoformat(value)


def _apply_event_patch(
    events: list[dict[str, str]],
    patch: EventPatch,
    request_date: str,
) -> bool:
    """Apply one EventPatch to the mutable events list; return True if something changed."""
    if patch.patch_type == "cancel_event" and patch.event_id:
        applied = False
        for event in events:
            if event.get("event_id") == patch.event_id:
                event["status"] = "cancelled"
                applied = True
        return applied

    if patch.patch_type == "cancel_bonus_scheduled":
        applied = False
        req = _parse_date(request_date)
        for event in events:
            desc = (event.get("description") or "").lower()
            if "bonus" not in desc:
                continue
            status = (event.get("status") or "").lower()
            if status not in ("scheduled", "pending"):
                continue
            settlement = (event.get("settlement_date") or event.get("event_date") or "")
            if settlement and _parse_date(settlement) >= req:
                event["status"] = "cancelled"
                applied = True
        return applied

    if patch.patch_type == "reschedule_salary_credits":
        new_date = (patch.details or {}).get("new_date")
        if not new_date:
            return False
        applied = False
        req = _parse_date(request_date)
        for event in events:
            if (event.get("category") or "").lower() != "salary":
                continue
            if (event.get("direction") or "").lower() != "credit":
                continue
            status = (event.get("status") or "").lower()
            if status not in ("scheduled", "pending"):
                continue
            settlement = (event.get("settlement_date") or event.get("event_date") or "")
            if not settlement:
                continue
            if _parse_date(settlement) >= req:
                event["settlement_date"] = new_date
                event["event_date"] = new_date
                applied = True
        return applied

    return False


def apply_message_patches(
    events: list[dict[str, str]],
    messages: list[dict[str, str]],
    request_date: str,
) -> tuple[list[dict[str, str]], int]:
    """Interpret messages and mutate events (cancel/reschedule) before FX resolution."""
    patched = [dict(event) for event in events]
    event_patches, _ = interpret_messages(messages, request_date)
    applied = 0
    for patch in event_patches:
        if _apply_event_patch(patched, patch, request_date):
            applied += 1
    return patched, applied
