from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserContextRow:
    """One user request and financial context loaded from user_context.csv."""

    user_id: str
    request_id: str
    data_source: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: list[str]
    expense_categories_to_protect: list[str]
    expense_categories_user_is_willing_to_reduce: list[str]
    expense_categories_user_is_willing_to_stop: list[str]
    payment_methods_user_will_consider: list[str]
    max_installment_months: int | None
    request_date: str
    request_type: str
    requested_amount: float
    desired_completion_date: str
    allows_partial_payment: bool
    request_text: str
    payment_options: list[dict[str, str]]
    financial_events: list[dict[str, str]]
    messages: list[dict[str, str]]
    images: list[dict[str, str]]
    sample_labels: dict[str, str] | None


@dataclass
class ResolvedCashEvent:
    """Single cash movement in home currency after resolution rules."""

    event_id: str
    settlement_date: str
    event_date: str
    direction: str
    category: str
    event_type: str
    description: str
    status: str
    flexibility: str
    minimum_allowed_amount: float | None
    original_currency: str
    original_amount: float
    amount_home: float
    home_currency: str
    linked_event_id: str
    amount_source: str  # csv | images_json


@dataclass
class ExcludedEvent:
    """Event omitted from the cash ledger with a machine-readable reason."""

    event_id: str
    reason: str


@dataclass
class ResolvedLedger:
    """Resolved events, exclusions, and 90-day forecast for one user."""

    user_id: str
    request_id: str
    request_date: str
    home_currency: str
    starting_balance_home: float
    minimum_balance_to_keep: float
    cash_events: list[ResolvedCashEvent] = field(default_factory=list)
    excluded_events: list[ExcludedEvent] = field(default_factory=list)
    message_patch_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    forecast: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize ledger for resolved_ledgers.json."""
        return {
            "user_id": self.user_id,
            "request_id": self.request_id,
            "request_date": self.request_date,
            "home_currency": self.home_currency,
            "starting_balance_home": self.starting_balance_home,
            "minimum_balance_to_keep": self.minimum_balance_to_keep,
            "message_patch_count": self.message_patch_count,
            "metadata": self.metadata,
            "forecast": self.forecast,
            "cash_events": [
                {
                    "event_id": e.event_id,
                    "settlement_date": e.settlement_date,
                    "event_date": e.event_date,
                    "direction": e.direction,
                    "category": e.category,
                    "event_type": e.event_type,
                    "description": e.description,
                    "status": e.status,
                    "flexibility": e.flexibility,
                    "minimum_allowed_amount": e.minimum_allowed_amount,
                    "original_currency": e.original_currency,
                    "original_amount": e.original_amount,
                    "amount_home": e.amount_home,
                    "home_currency": e.home_currency,
                    "linked_event_id": e.linked_event_id,
                    "amount_source": e.amount_source,
                }
                for e in self.cash_events
            ],
            "excluded_events": [
                {"event_id": x.event_id, "reason": x.reason} for x in self.excluded_events
            ],
        }
