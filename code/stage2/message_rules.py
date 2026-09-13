"""
Deterministic interpretation of untrusted messages for ledger patches and forecast.

Messages may clarify, amend, delay, or cancel financial facts; embedded instructions
never override challenge rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ForecastAdjustment:
    """Describes a message-derived change to projected cashflows."""

    adjustment_id: str
    adjustment_type: str
    recurrence_key: str | None
    event_id: str | None
    flow_date: str | None
    amount_home: float | None
    direction: str | None
    category: str | None
    details: dict[str, Any]


@dataclass
class EventPatch:
    """Instruction to mutate raw financial_events before FX resolution."""

    patch_type: str
    event_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_SALARY_AMOUNT_RE = re.compile(
    r"(?:"
    r"naik menjadi|increased to|reduced to|temporary monthly pay is|"
    r"regular salary of|regular salary for the next payroll is|"
    r"first salary will be|monthly salary has increased to|"
    r"confirmed salary is|gaji pokok yang dikonfirmasi adalah|"
    r"gaji bulanan sementara anda adalah|gaji bulanan anda naik menjadi|"
    r"your next salary is reduced to|salary is reduced to|"
    r"regular salary of"
    r")"
    r"\s*(?:(USD|EUR|INR|IDR|ZAR)\s*)?([\d][\d,]*\.?\d*)",
    re.IGNORECASE,
)
_INVOICE_AMOUNT_RE = re.compile(
    r"(?:client approved an invoice payment of|menyetujui pembayaran faktur sebesar)\s*"
    r"(?:(USD|EUR|INR|IDR|ZAR)\s*)?([\d][\d,]*\.?\d*)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(
    r"(?:increases?|naik)\s+(?:monthly\s+)?rent\s+by\s+(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    """Lowercase message text for phrase matching."""
    return (text or "").lower()


def _parse_amount(raw: str) -> float:
    """Parse numeric amount strings that may contain thousands separators."""
    return float(raw.replace(",", ""))


def _extract_salary_amount(text: str) -> tuple[str | None, float] | None:
    """Extract (currency, amount) from salary-related phrases, or None."""
    match = _SALARY_AMOUNT_RE.search(text)
    if not match:
        return None
    currency = (match.group(1) or "").strip().upper() or None
    amount = _parse_amount(match.group(2))
    if amount < 50 and not currency:
        return None
    return currency, amount


def _extract_invoice_amount(text: str) -> tuple[str | None, float] | None:
    """Extract (currency, amount) from approved-invoice phrases, or None."""
    match = _INVOICE_AMOUNT_RE.search(text)
    if not match:
        return None
    currency = (match.group(1) or "").strip().upper() or None
    return currency, _parse_amount(match.group(2))


def _extract_dates(text: str) -> list[str]:
    """Find ISO dates (20YY-MM-DD) mentioned in message text."""
    return _DATE_RE.findall(text)


def interpret_messages(
    messages: list[dict[str, str]],
    request_date: str,
) -> tuple[list[EventPatch], list[ForecastAdjustment]]:
    """Return event patches (Stage 2 ledger) and forecast adjustments (90-day sim)."""
    event_patches: list[EventPatch] = []
    forecast_adjustments: list[ForecastAdjustment] = []
    seen_adj: set[str] = set()

    def add_adj(adj: ForecastAdjustment) -> None:
        """Append a forecast adjustment once per adjustment_id."""
        if adj.adjustment_id in seen_adj:
            return
        seen_adj.add(adj.adjustment_id)
        forecast_adjustments.append(adj)

    for index, message in enumerate(messages):
        text = message.get("message_text") or ""
        lower = _norm(text)
        related = (message.get("related_event_id") or "").strip()
        msg_id = message.get("message_id") or f"idx_{index}"

        if related and any(
            phrase in lower
            for phrase in (
                "has not reached your account",
                "has not been credited",
                "refund has been initiated",
                "still processing",
                "payment processing",
                "reversal has not been posted",
            )
        ):
            event_patches.append(
                EventPatch(
                    patch_type="cancel_event",
                    event_id=related,
                    details={"reason": "message_unsettled_credit"},
                )
            )

        if "transfer between your two accounts" in lower or (
            "matching debit and credit" in lower and "two accounts" in lower
        ):
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_internal_transfer",
                    adjustment_type="exclude_internal_transfer_pairs",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction=None,
                    category=None,
                    details={},
                )
            )

        if ("payout is still pending" in lower or "still pending" in lower) and (
            "withdrawable" in lower or "payout" in lower or "taskloop" in lower or "quickcrew" in lower
        ):
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_pending_service_payout",
                    adjustment_type="cancel_recurring_credits",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="credit",
                    category=None,
                    details={"exclude_known_future_credits": True},
                )
            )
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_pending_gig_substring",
                    adjustment_type="cancel_recurrence_substring",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="credit",
                    category=None,
                    details={
                        "description_substrings": [
                            "quickcrew",
                            "taskloop",
                            "ridegrid",
                            "gig",
                            "freelance",
                            "payout",
                        ],
                        "include_known_future": True,
                    },
                )
            )

        if "contract has ended" in lower and (
            "no off-season income" in lower or "no off-season" in lower
        ):
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_seasonal_ended",
                    adjustment_type="cancel_recurring_credits",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="credit",
                    category="salary",
                    details={},
                )
            )

        if "bonus" in lower and any(
            phrase in lower
            for phrase in (
                "still waiting",
                "menunggu",
                "not been approved",
                "belum disetujui",
                "belum disetujui",
                "payment date have not been approved",
                "belum disetujui",
            )
        ):
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_bonus_pending",
                    adjustment_type="cancel_recurrence_substring",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="credit",
                    category=None,
                    details={"description_substrings": ["bonus", "performance bonus"]},
                )
            )
            event_patches.append(
                EventPatch(
                    patch_type="cancel_bonus_scheduled",
                    event_id=None,
                    details={"message_id": msg_id},
                )
            )

        if "commission" in lower and any(
            phrase in lower
            for phrase in (
                "not approved",
                "belum disetujui",
                "belum disetujui",
                "not included",
                "tidak masuk pembayaran",
                "running transactions",
            )
        ):
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_commission_unapproved",
                    adjustment_type="cancel_recurrence_substring",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="credit",
                    category=None,
                    details={"description_substrings": ["commission"]},
                )
            )

        if "no units have been sold" in lower and "cash proceeds" in lower:
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_no_investment_proceeds",
                    adjustment_type="cancel_recurrence_substring",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="credit",
                    category=None,
                    details={"description_substrings": ["investment", "portfolio", "dividend"]},
                )
            )

        if "prize claim" in lower and "has not been credited" in lower:
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_prize_pending",
                    adjustment_type="cancel_recurring_credits",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="credit",
                    category=None,
                    details={"exclude_known_future_credits": True},
                )
            )

        percent = _PERCENT_RE.search(text)
        if percent and "rent" in lower:
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_rent_increase_pct",
                    adjustment_type="scale_recurring_rent",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="debit",
                    category="rent",
                    details={"multiplier": 1.0 + float(percent.group(1)) / 100.0},
                )
            )

        if "client approved" in lower or "menyetujui pembayaran" in lower:
            parsed = _extract_invoice_amount(text)
            dates = _extract_dates(text)
            if parsed and dates:
                currency, amount = parsed
                add_adj(
                    ForecastAdjustment(
                        adjustment_id=f"{msg_id}_approved_invoice_only",
                        adjustment_type="cap_invoice_payout",
                        recurrence_key=None,
                        event_id=None,
                        flow_date=dates[0],
                        amount_home=amount,
                        direction="credit",
                        category=None,
                        details={"currency": currency, "awaiting_other_invoices": True},
                    )
                )

        salary_parsed = _extract_salary_amount(text)
        if salary_parsed:
            currency, amount = salary_parsed
            dates = _extract_dates(text)
            effective = dates[0] if dates else request_date
            if "resumes on" in lower and dates:
                effective = dates[0]
            if "applies from" in lower or "berlaku mulai" in lower:
                for d in dates:
                    if d >= request_date:
                        effective = d
                        break
            if "confirmed credit date is" in lower or "confirmed for" in lower:
                effective = dates[0] if dates else effective
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_salary_override",
                    adjustment_type="override_salary_from_date",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=effective,
                    amount_home=amount,
                    direction="credit",
                    category="salary",
                    details={"currency": currency},
                )
            )

        if "payroll date" in lower or "payroll record" in lower:
            if "expected on" in lower or "replaces the payroll date" in lower:
                dates = _extract_dates(text)
                if dates:
                    event_patches.append(
                        EventPatch(
                            patch_type="reschedule_salary_credits",
                            event_id=None,
                            details={"new_date": dates[0], "message_id": msg_id},
                        )
                    )
                    add_adj(
                        ForecastAdjustment(
                            adjustment_id=f"{msg_id}_shift_salary_date",
                            adjustment_type="shift_salary_credit_dates",
                            recurrence_key=None,
                            event_id=None,
                            flow_date=dates[0],
                            amount_home=None,
                            direction="credit",
                            category="salary",
                            details={"anchor_day": dates[0][-2:]},
                        )
                    )

        if "household employment record has ended" in lower or "income that has ended" in lower:
            add_adj(
                ForecastAdjustment(
                    adjustment_id=f"{msg_id}_ended_income",
                    adjustment_type="cancel_recurrence_substring",
                    recurrence_key=None,
                    event_id=None,
                    flow_date=None,
                    amount_home=None,
                    direction="credit",
                    category="salary",
                    details={"description_substrings": ["payroll", "employer"]},
                )
            )

    return event_patches, forecast_adjustments
