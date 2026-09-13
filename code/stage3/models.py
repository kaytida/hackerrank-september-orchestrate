"""Output schema and internal plan/decision datatypes for Stage 3."""

from __future__ import annotations

from dataclasses import dataclass


OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


@dataclass
class DecisionRow:
    """Deterministic decision fields for one request before explanation text."""

    request_id: str
    request_date: str
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str

    def to_output_dict(self, explanation: str) -> dict[str, str]:
        """Merge decision fields with decision_explanation for CSV rows."""
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": _fmt_amount(self.amount_safe_to_pay),
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan or "none",
            "earliest_date_for_full_payment": self.earliest_date_for_full_payment,
            "spending_changes_needed": self.spending_changes_needed or "none",
            "decision_explanation": explanation,
        }


@dataclass
class CandidatePlan:
    """Internal representation of a payment option under evaluation."""

    affordability_status: str
    recommended_payment_method: str
    payment_plan: list[tuple[str, float]]
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    total_paid: float
    payment_count: int
    first_payment_date: str
    payment_option_id: str | None
    completes_by_deadline: bool


def _fmt_amount(value: float) -> str:
    """Format monetary amounts for CSV (integers without .0 when whole)."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text
