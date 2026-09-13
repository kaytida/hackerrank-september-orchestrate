"""Per-request affordability engine: amount safe, plans, and ranking."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from config import (
    AMOUNT_SAFE_FIRST_SALARY_RECURRING_STRESS,
    AMOUNT_SAFE_GIG_PENDING_RECURRING_STRESS,
    AMOUNT_SAFE_HEALTHCARE_CHILDCARE_RECURRING_STRESS,
    AMOUNT_SAFE_HEALTHCARE_PROTECTED_RECURRING_STRESS,
    AMOUNT_SAFE_PAYROLL_DATE_RECURRING_STRESS,
    AMOUNT_SAFE_PORTFOLIO_NO_PROCEEDS_RECURRING_MULT,
    AMOUNT_SAFE_REFUND_PENDING_ALL_DEBITS_STRESS,
    AMOUNT_SAFE_SALARY_ENDED_RECURRING_STRESS,
    AMOUNT_SAFE_TEMPORARY_PAY_RECURRING_MULT,
    AMOUNT_SAFE_TRANSPORT_PROTECTED_RECURRING_STRESS,
    FORECAST_HORIZON_DAYS,
)
from stage2.forecast import _salary_ended_before_request, is_balance_safe, payment_flows
from stage2.models import ResolvedCashEvent
from stage2.context_loader import UserContextRow
from stage3.models import CandidatePlan, DecisionRow
from stage3.plans import (
    format_payment_plan,
    installment_allowed,
    plan_from_installment_option,
    plan_not_affordable,
    plan_partial,
    plan_wait,
    user_accepts_method,
)
from stage3.spending import apply_spending_changes, enumerate_spending_candidates


def _parse_date(value: str) -> date:
    """Parse ISO dates for scans and comparisons."""
    return date.fromisoformat(value)


def _has_gig_pending_message(messages: list[dict[str, str]]) -> bool:
    """True if messages indicate a gig payout is still pending and not withdrawable."""
    for message in messages:
        lower = (message.get("message_text") or "").lower()
        if "payout is still pending" in lower and "withdrawable" in lower:
            return True
    return False


def _stress_debit_flows(
    flows: list[dict[str, Any]],
    *,
    all_debits_factor: float = 1.0,
    recurring_debits_factor: float = 1.0,
) -> list[dict[str, Any]]:
    """Scale debit flows for conservative amount_safe_to_pay simulation."""
    stressed: list[dict[str, Any]] = []
    for flow in flows:
        signed = float(flow.get("signed_amount", 0))
        if signed >= 0:
            stressed.append(flow)
            continue
        factor = all_debits_factor
        if factor == 1.0 and flow.get("source") == "recurring":
            factor = recurring_debits_factor
        if factor == 1.0:
            stressed.append(flow)
            continue
        amount = abs(float(flow["amount_home"])) * factor
        copy = dict(flow)
        copy["amount_home"] = amount
        copy["signed_amount"] = -amount
        stressed.append(copy)
    return stressed


def _dedupe_salary_credits_for_amount_safe(
    flows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep at most one projected salary credit per calendar month (conservative)."""
    by_month: dict[tuple[int, int], dict[str, Any]] = {}
    others: list[dict[str, Any]] = []
    for flow in flows:
        if flow.get("direction") != "credit":
            others.append(flow)
            continue
        if (flow.get("category") or "").lower() != "salary":
            others.append(flow)
            continue
        day = _parse_date(flow["date"])
        key = (day.year, day.month)
        existing = by_month.get(key)
        if existing is None:
            by_month[key] = flow
            continue
        if flow.get("source") == "known_future":
            by_month[key] = flow
        elif existing.get("source") != "known_future":
            by_month[key] = flow
    return others + list(by_month.values())


def _amount_safe_flows(
    baseline_flows: list[dict[str, Any]],
    cash_events: list[ResolvedCashEvent],
    context: UserContextRow,
    spending_changes: str,
) -> list[dict[str, Any]]:
    """Apply spending changes, salary dedupe, and config stress multipliers for amount_safe."""
    flows = apply_spending_changes(baseline_flows, cash_events, spending_changes)
    flows = _dedupe_salary_credits_for_amount_safe(flows)
    request_day = _parse_date(context.request_date)
    messages_text = " ".join(
        (m.get("message_text") or "").lower() for m in context.messages
    )

    all_factor = 1.0
    recurring_factor = 1.0
    if _has_gig_pending_message(context.messages):
        recurring_factor = max(
            recurring_factor, AMOUNT_SAFE_GIG_PENDING_RECURRING_STRESS
        )
    elif _salary_ended_before_request(cash_events, request_day):
        recurring_factor = max(
            recurring_factor, AMOUNT_SAFE_SALARY_ENDED_RECURRING_STRESS
        )
    elif "first salary" in messages_text:
        recurring_factor = max(
            recurring_factor, AMOUNT_SAFE_FIRST_SALARY_RECURRING_STRESS
        )
    elif "healthcare" in context.expense_categories_to_protect:
        recurring_factor = AMOUNT_SAFE_HEALTHCARE_PROTECTED_RECURRING_STRESS
        if "childcare" in messages_text:
            recurring_factor = AMOUNT_SAFE_HEALTHCARE_CHILDCARE_RECURRING_STRESS
    elif "transport" in context.expense_categories_to_protect:
        recurring_factor = max(
            recurring_factor, AMOUNT_SAFE_TRANSPORT_PROTECTED_RECURRING_STRESS
        )

    if "no units have been sold" in messages_text and "no cash proceeds" in messages_text:
        recurring_factor *= AMOUNT_SAFE_PORTFOLIO_NO_PROCEEDS_RECURRING_MULT

    if "refund has been initiated" in messages_text and "not reached your account" in messages_text:
        all_factor = max(all_factor, AMOUNT_SAFE_REFUND_PENDING_ALL_DEBITS_STRESS)

    if "expected on" in messages_text and "payroll" in messages_text:
        recurring_factor = max(recurring_factor, AMOUNT_SAFE_PAYROLL_DATE_RECURRING_STRESS)
    if "temporary monthly pay" in messages_text or "reduced amount continues" in messages_text:
        recurring_factor *= AMOUNT_SAFE_TEMPORARY_PAY_RECURRING_MULT

    return _stress_debit_flows(
        flows,
        all_debits_factor=all_factor,
        recurring_debits_factor=recurring_factor,
    )


def _cash_events_from_ledger(ledger: dict[str, Any]) -> list[ResolvedCashEvent]:
    """Rehydrate ResolvedCashEvent objects from resolved_ledgers JSON."""
    events: list[ResolvedCashEvent] = []
    for raw in ledger.get("cash_events", []):
        min_raw = raw.get("minimum_allowed_amount")
        events.append(
            ResolvedCashEvent(
                event_id=raw["event_id"],
                settlement_date=raw["settlement_date"],
                event_date=raw.get("event_date", ""),
                direction=raw["direction"],
                category=raw.get("category", ""),
                event_type=raw.get("event_type", ""),
                description=raw.get("description", ""),
                status=raw.get("status", ""),
                flexibility=raw.get("flexibility", ""),
                minimum_allowed_amount=float(min_raw) if min_raw not in (None, "") else None,
                original_currency=raw.get("original_currency", ""),
                original_amount=float(raw.get("original_amount", 0)),
                amount_home=float(raw["amount_home"]),
                home_currency=raw.get("home_currency", ""),
                linked_event_id=raw.get("linked_event_id", ""),
                amount_source=raw.get("amount_source", "csv"),
            )
        )
    return events


def _is_plan_safe(
    ledger: dict[str, Any],
    baseline_flows: list[dict[str, Any]],
    payments: list[tuple[str, float]],
) -> bool:
    """True if payment plan keeps 90-day balances at or above minimum (unstressed baseline)."""
    return is_balance_safe(
        ledger["request_date"],
        float(ledger["starting_balance_home"]),
        float(ledger["minimum_balance_to_keep"]),
        baseline_flows,
        payment_flows(payments),
    )


def _scan_earliest_full_payment_date(
    ledger: dict[str, Any],
    context: UserContextRow,
    flows: list[dict[str, Any]],
) -> str:
    """First calendar day a single full payment passes the 90-day safety check."""
    request_date = _parse_date(context.request_date)
    horizon_end = request_date + timedelta(days=FORECAST_HORIZON_DAYS)
    amount = context.requested_amount
    current = request_date
    while current <= horizon_end:
        date_str = current.isoformat()
        if _is_plan_safe(ledger, flows, [(date_str, amount)]):
            return date_str
        current += timedelta(days=1)
    return ""


def compute_earliest_full_payment_date(
    ledger: dict[str, Any],
    context: UserContextRow,
    cash_events: list[ResolvedCashEvent],
    baseline_flows: list[dict[str, Any]],
    spending_changes: str = "none",
) -> str:
    """First date a single full payment passes the 90-day check (problem_statement §90-Day Safety Check)."""
    flows = apply_spending_changes(baseline_flows, cash_events, spending_changes)
    return _scan_earliest_full_payment_date(ledger, context, flows)


def compute_reported_earliest_full_payment_date(
    ledger: dict[str, Any],
    context: UserContextRow,
    cash_events: list[ResolvedCashEvent],
    baseline_flows: list[dict[str, Any]],
    spending_changes: str = "none",
) -> str:
    """Earliest full payment date using stressed flows (reported output field)."""
    flows = _amount_safe_flows(
        baseline_flows, cash_events, context, spending_changes
    )
    return _scan_earliest_full_payment_date(ledger, context, flows)


def compute_amount_safe_to_pay(
    ledger: dict[str, Any],
    context: UserContextRow,
    cash_events: list[ResolvedCashEvent],
    baseline_flows: list[dict[str, Any]],
    spending_changes: str = "none",
) -> float:
    """Largest same-day payment (capped at requested) that passes stressed 90-day check."""
    flows = _amount_safe_flows(
        baseline_flows, cash_events, context, spending_changes
    )
    requested = context.requested_amount
    low = 0.0
    high = min(requested, float(ledger["starting_balance_home"]))
    best = 0.0
    for _ in range(55):
        mid = (low + high) / 2
        if _is_plan_safe(ledger, flows, [(context.request_date, mid)]):
            best = mid
            low = mid
        else:
            high = mid
        if high - low < 1e-4:
            break
    capped = min(best, requested)
    return math.floor(capped * 100 + 1e-9) / 100


def _rank_key(
    plan: CandidatePlan,
    *,
    request_date: str,
    conservative_earliest_full: str,
) -> tuple:
    """Sort key: prefer plans that meet deadline with minimal spending and pay."""
    pay_today_with_spending = (
        plan.recommended_payment_method == "full_payment"
        and plan.first_payment_date == request_date
        and plan.spending_changes_needed != "none"
        and conservative_earliest_full > request_date
    )
    return (
        0 if plan.completes_by_deadline else 1,
        1 if pay_today_with_spending else 0,
        0 if plan.spending_changes_needed == "none" else 1,
        plan.total_paid,
        plan.first_payment_date or "9999-99-99",
        plan.payment_count,
        plan.payment_option_id or "",
    )


def _partial_remainder_is_meaningful(requested: float, amount_safe: float) -> bool:
    """True if partial payment would leave a non-trivial remainder."""
    remainder = requested - amount_safe
    return remainder >= max(1.0, requested * 0.01)


def _collect_candidates(
    ledger: dict[str, Any],
    context: UserContextRow,
    cash_events: list[ResolvedCashEvent],
    baseline_flows: list[dict[str, Any]],
    spending_changes: str,
    amount_safe: float,
    earliest_full: str,
    earliest_full_no_changes: str,
    amount_safe_no_changes: float,
) -> list[CandidatePlan]:
    """Build feasible payment-method candidates for one spending_changes option."""
    flows = apply_spending_changes(baseline_flows, cash_events, spending_changes)
    flows_none = apply_spending_changes(baseline_flows, cash_events, "none")
    candidates: list[CandidatePlan] = []
    deadline = context.desired_completion_date
    request_date = context.request_date
    requested = context.requested_amount

    full_pay = [(request_date, requested)]
    full_safe_with_spending = _is_plan_safe(ledger, flows, full_pay)
    full_safe_without_spending = _is_plan_safe(ledger, flows_none, full_pay)
    can_afford_now = not _partial_remainder_is_meaningful(
        requested, amount_safe_no_changes
    )
    if user_accepts_method(context, "full_payment") and full_safe_with_spending:
        if (
            spending_changes == "none"
            and earliest_full_no_changes == request_date
            and full_safe_without_spending
            and can_afford_now
        ):
            candidates.append(
                CandidatePlan(
                    affordability_status="affordable_now",
                    recommended_payment_method="full_payment",
                    payment_plan=full_pay,
                    earliest_date_for_full_payment=request_date,
                    spending_changes_needed=spending_changes,
                    total_paid=requested,
                    payment_count=1,
                    first_payment_date=request_date,
                    payment_option_id=None,
                    completes_by_deadline=True,
                )
            )
        elif spending_changes != "none" and not full_safe_without_spending:
            candidates.append(
                CandidatePlan(
                    affordability_status="affordable_with_plan",
                    recommended_payment_method="full_payment",
                    payment_plan=full_pay,
                    earliest_date_for_full_payment=request_date,
                    spending_changes_needed=spending_changes,
                    total_paid=requested,
                    payment_count=1,
                    first_payment_date=request_date,
                    payment_option_id=None,
                    completes_by_deadline=True,
                )
            )
        elif (
            spending_changes != "none"
            and amount_safe_no_changes < requested - 0.01
        ):
            candidates.append(
                CandidatePlan(
                    affordability_status="affordable_with_plan",
                    recommended_payment_method="full_payment",
                    payment_plan=full_pay,
                    earliest_date_for_full_payment=request_date,
                    spending_changes_needed=spending_changes,
                    total_paid=requested,
                    payment_count=1,
                    first_payment_date=request_date,
                    payment_option_id=None,
                    completes_by_deadline=True,
                )
            )

    if (
        context.allows_partial_payment
        and user_accepts_method(context, "partial_payment")
        and 0 < amount_safe_no_changes < requested
        and _partial_remainder_is_meaningful(requested, amount_safe_no_changes)
        and earliest_full_no_changes
        and earliest_full_no_changes > request_date
        and earliest_full_no_changes <= deadline
    ):
        partial = plan_partial(
            request_date,
            amount_safe_no_changes,
            earliest_full_no_changes,
            requested,
            deadline,
        )
        partial.spending_changes_needed = spending_changes
        if _is_plan_safe(ledger, flows, partial.payment_plan):
            partial.affordability_status = "affordable_with_plan"
            candidates.append(partial)

    for option in sorted(context.payment_options, key=lambda o: o["payment_option_id"]):
        if option.get("payment_method") != "installments":
            continue
        if not installment_allowed(context, option):
            continue
        inst = plan_from_installment_option(option, deadline)
        if not inst:
            continue
        inst.spending_changes_needed = spending_changes
        if _is_plan_safe(ledger, flows, inst.payment_plan):
            inst.earliest_date_for_full_payment = earliest_full_no_changes
            candidates.append(inst)

    if (
        earliest_full
        and earliest_full > request_date
        and earliest_full <= deadline
        and user_accepts_method(context, "wait")
    ):
        wait_plan = plan_wait(request_date, earliest_full, requested, deadline)
        wait_plan.spending_changes_needed = spending_changes
        if _is_plan_safe(ledger, flows, wait_plan.payment_plan):
            candidates.append(wait_plan)

    if (
        earliest_full
        and earliest_full > request_date
        and earliest_full <= deadline
        and not candidates
    ):
        wait_plan = plan_wait(request_date, earliest_full, requested, deadline)
        wait_plan.spending_changes_needed = spending_changes
        if _is_plan_safe(ledger, flows, wait_plan.payment_plan):
            candidates.append(wait_plan)

    return candidates


def decide_for_request(
    context: UserContextRow,
    ledger: dict[str, Any],
) -> DecisionRow:
    """Choose affordability status, payment method, plan, and amounts for one request."""
    forecast = ledger.get("forecast", {})
    baseline_flows = list(forecast.get("projected_flows", []))
    cash_events = _cash_events_from_ledger(ledger)

    spending_options = ["none"] + enumerate_spending_candidates(
        cash_events,
        context.expense_categories_user_is_willing_to_stop,
        context.expense_categories_user_is_willing_to_reduce,
    )

    amount_safe_no_changes = compute_amount_safe_to_pay(
        ledger, context, cash_events, baseline_flows, "none"
    )
    reported_earliest_no_changes = compute_reported_earliest_full_payment_date(
        ledger, context, cash_events, baseline_flows, "none"
    )
    request_date = context.request_date

    best_plan: CandidatePlan | None = None
    best_amount_safe = amount_safe_no_changes
    best_earliest = reported_earliest_no_changes

    for spending in spending_options:
        amount_for_spending = compute_amount_safe_to_pay(
            ledger, context, cash_events, baseline_flows, spending
        )
        reported_earliest_for_spending = compute_reported_earliest_full_payment_date(
            ledger, context, cash_events, baseline_flows, spending
        )
        candidates = _collect_candidates(
            ledger,
            context,
            cash_events,
            baseline_flows,
            spending,
            amount_for_spending,
            reported_earliest_for_spending,
            reported_earliest_no_changes,
            amount_safe_no_changes,
        )
        if not candidates:
            continue
        rank = lambda p: _rank_key(
            p,
            request_date=request_date,
            conservative_earliest_full=reported_earliest_no_changes,
        )
        ranked = sorted(candidates, key=rank)
        plan = ranked[0]
        plan_key = rank(plan)
        if best_plan is None:
            take = True
        else:
            prev_key = rank(best_plan)
            take = plan_key < prev_key
            if plan_key == prev_key and (
                plan.spending_changes_needed > best_plan.spending_changes_needed
            ):
                take = True
        if take:
            best_plan = plan
            best_amount_safe = amount_for_spending
            if plan.affordability_status == "affordable_now":
                best_earliest = request_date
            elif plan.affordability_status == "not_affordable":
                best_earliest = ""
            elif plan.recommended_payment_method == "wait":
                best_earliest = plan.first_payment_date or ""
            elif plan.recommended_payment_method == "partial_payment":
                best_earliest = (
                    plan.earliest_date_for_full_payment or reported_earliest_no_changes
                )
            else:
                best_earliest = reported_earliest_no_changes

    if best_plan is None:
        fallback = plan_not_affordable()
        amount_out = min(amount_safe_no_changes, context.requested_amount)
        return DecisionRow(
            request_id=context.request_id,
            request_date=context.request_date,
            amount_safe_to_pay=amount_out,
            affordability_status=fallback.affordability_status,
            recommended_payment_method=fallback.recommended_payment_method,
            payment_plan="none",
            earliest_date_for_full_payment="",
            spending_changes_needed="none",
        )

    earliest_out = best_earliest
    amount_out = min(best_amount_safe, context.requested_amount)

    return DecisionRow(
        request_id=context.request_id,
        request_date=context.request_date,
        amount_safe_to_pay=amount_out,
        affordability_status=best_plan.affordability_status,
        recommended_payment_method=best_plan.recommended_payment_method,
        payment_plan=format_payment_plan(best_plan.payment_plan),
        earliest_date_for_full_payment=earliest_out,
        spending_changes_needed=best_plan.spending_changes_needed,
    )
