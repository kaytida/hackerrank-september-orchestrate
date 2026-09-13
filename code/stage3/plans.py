from __future__ import annotations

from datetime import date, timedelta

from stage2.models import UserContextRow
from stage3.models import CandidatePlan


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _fmt_plan(payments: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return [(d, float(a)) for d, a in payments if a > 0]


def expand_installment_option(option: dict[str, str]) -> list[tuple[str, float]]:
    first = _parse_date(option["first_payment_date"])
    freq = int(option["payment_frequency_days"])
    count = int(option["number_of_payments"])
    amount = float(option["payment_amount"])
    payments: list[tuple[str, float]] = []
    current = first
    for _ in range(count):
        payments.append((current.isoformat(), amount))
        current += timedelta(days=freq)
    return payments


def build_full_payment_plan(request_date: str, amount: float) -> list[tuple[str, float]]:
    return [(request_date, amount)]


def build_partial_plan(
    request_date: str, pay_today: float, remainder_date: str, requested_amount: float
) -> list[tuple[str, float]]:
    remainder = requested_amount - pay_today
    return _fmt_plan([(request_date, pay_today), (remainder_date, remainder)])


def plan_from_installment_option(
    option: dict[str, str],
    deadline: str,
) -> CandidatePlan | None:
    payments = expand_installment_option(option)
    if not payments:
        return None
    last_date = payments[-1][0]
    total = sum(amount for _, amount in payments)
    return CandidatePlan(
        affordability_status="affordable_with_plan",
        recommended_payment_method="installments",
        payment_plan=payments,
        earliest_date_for_full_payment="",
        spending_changes_needed="none",
        total_paid=total,
        payment_count=len(payments),
        first_payment_date=payments[0][0],
        payment_option_id=option["payment_option_id"],
        completes_by_deadline=last_date <= deadline,
    )


def plan_full_payment(
    request_date: str,
    requested_amount: float,
    deadline: str,
    pay_date: str | None = None,
) -> CandidatePlan:
    when = pay_date or request_date
    return CandidatePlan(
        affordability_status="affordable_now" if when == request_date else "affordable_later",
        recommended_payment_method="wait" if when != request_date else "full_payment",
        payment_plan=[(when, requested_amount)],
        earliest_date_for_full_payment=when,
        spending_changes_needed="none",
        total_paid=requested_amount,
        payment_count=1,
        first_payment_date=when,
        payment_option_id=None,
        completes_by_deadline=when <= deadline,
    )


def plan_wait(request_date: str, pay_date: str, requested_amount: float, deadline: str) -> CandidatePlan:
    return CandidatePlan(
        affordability_status="affordable_later",
        recommended_payment_method="wait",
        payment_plan=[(pay_date, requested_amount)],
        earliest_date_for_full_payment=pay_date,
        spending_changes_needed="none",
        total_paid=requested_amount,
        payment_count=1,
        first_payment_date=pay_date,
        payment_option_id=None,
        completes_by_deadline=pay_date <= deadline,
    )


def plan_partial(
    request_date: str,
    pay_today: float,
    remainder_date: str,
    requested_amount: float,
    deadline: str,
) -> CandidatePlan:
    payments = build_partial_plan(request_date, pay_today, remainder_date, requested_amount)
    return CandidatePlan(
        affordability_status="affordable_with_plan",
        recommended_payment_method="partial_payment",
        payment_plan=payments,
        earliest_date_for_full_payment=remainder_date,
        spending_changes_needed="none",
        total_paid=requested_amount,
        payment_count=2,
        first_payment_date=request_date,
        payment_option_id=None,
        completes_by_deadline=remainder_date <= deadline,
    )


def plan_not_affordable() -> CandidatePlan:
    return CandidatePlan(
        affordability_status="not_affordable",
        recommended_payment_method="not_recommended",
        payment_plan=[],
        earliest_date_for_full_payment="",
        spending_changes_needed="none",
        total_paid=0.0,
        payment_count=0,
        first_payment_date="",
        payment_option_id=None,
        completes_by_deadline=False,
    )


def format_payment_plan(payments: list[tuple[str, float]]) -> str:
    if not payments:
        return "none"
    parts = []
    for pay_date, amount in payments:
        if abs(amount - round(amount)) < 1e-9:
            parts.append(f"{pay_date}:{int(round(amount))}")
        else:
            parts.append(f"{pay_date}:{amount:.2f}")
    return "|".join(parts)


def user_accepts_method(context: UserContextRow, method: str) -> bool:
    allowed = context.payment_methods_user_will_consider
    if method == "wait":
        return "full_payment" in allowed
    if method == "not_recommended":
        return True
    return method in allowed


def installment_allowed(context: UserContextRow, option: dict[str, str]) -> bool:
    if "installments" not in context.payment_methods_user_will_consider:
        return False
    if context.max_installment_months is None:
        return False
    months = int(option["number_of_payments"])
    if option.get("payment_frequency_days"):
        freq = int(option["payment_frequency_days"])
        span_days = freq * max(months - 1, 0)
        approx_months = span_days / 30.0 + 1
        return approx_months <= context.max_installment_months + 0.5
    return months <= context.max_installment_months
