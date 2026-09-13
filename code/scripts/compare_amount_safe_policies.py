"""
Compare sample decisions under tuned vs policy amount_safe stress (evaluation only).

Tuned = historical sample-fitted margins (for before/after analysis).
Policy = current config.py constants (not fitted to gold).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

_CODE = Path(__file__).resolve().parents[1]
if str(_CODE) not in sys.path:
    sys.path.insert(0, str(_CODE))

from stage2.context_loader import load_user_context_rows
from stage3 import decide as decide_mod
from stage2.models import ResolvedCashEvent
from stage2.context_loader import UserContextRow
from stage3.decide import (
    _dedupe_salary_credits_for_amount_safe,
    _has_gig_pending_message,
    _parse_date,
    _stress_debit_flows,
    decide_for_request,
)
from stage3.spending import apply_spending_changes
from stage2.forecast import _salary_ended_before_request
from stage3.models import DecisionRow
from stage3.regression import COMPARE_FIELDS, _parse_amount, _amounts_close

TUNED = {
    "gig": 1.056024,
    "salary_ended": 1.06155,
    "first_salary": 1.2,
    "healthcare": 1.0863,
    "healthcare_childcare": 1.084,
    "transport": 1.16,
    "portfolio_mult": 0.92,
    "refund_all": 1.26,
    "payroll_date": 1.1,
    "temporary_pay_mult": 1.003,
}

def _policy_params_from_config() -> dict[str, float | None]:
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
    )

    return {
        "gig": AMOUNT_SAFE_GIG_PENDING_RECURRING_STRESS,
        "salary_ended": AMOUNT_SAFE_SALARY_ENDED_RECURRING_STRESS,
        "first_salary": AMOUNT_SAFE_FIRST_SALARY_RECURRING_STRESS,
        "healthcare": AMOUNT_SAFE_HEALTHCARE_PROTECTED_RECURRING_STRESS,
        "healthcare_childcare": AMOUNT_SAFE_HEALTHCARE_CHILDCARE_RECURRING_STRESS,
        "transport": AMOUNT_SAFE_TRANSPORT_PROTECTED_RECURRING_STRESS,
        "portfolio_mult": AMOUNT_SAFE_PORTFOLIO_NO_PROCEEDS_RECURRING_MULT,
        "refund_all": AMOUNT_SAFE_REFUND_PENDING_ALL_DEBITS_STRESS,
        "payroll_date": AMOUNT_SAFE_PAYROLL_DATE_RECURRING_STRESS,
        "temporary_pay_mult": AMOUNT_SAFE_TEMPORARY_PAY_RECURRING_MULT,
    }


def _amount_safe_flows_variant(
    baseline_flows: list[dict[str, Any]],
    cash_events: list[ResolvedCashEvent],
    context: UserContextRow,
    spending_changes: str,
    params: dict[str, float | None],
) -> list[dict[str, Any]]:
    flows = apply_spending_changes(baseline_flows, cash_events, spending_changes)
    flows = _dedupe_salary_credits_for_amount_safe(flows)
    request_day = _parse_date(context.request_date)
    messages_text = " ".join(
        (m.get("message_text") or "").lower() for m in context.messages
    )

    all_factor = 1.0
    recurring_factor = 1.0
    if _has_gig_pending_message(context.messages):
        recurring_factor = max(recurring_factor, float(params["gig"]))
    elif _salary_ended_before_request(cash_events, request_day):
        recurring_factor = max(recurring_factor, float(params["salary_ended"]))
    elif "first salary" in messages_text:
        recurring_factor = max(recurring_factor, float(params["first_salary"]))
    elif "healthcare" in context.expense_categories_to_protect:
        recurring_factor = float(params["healthcare"])
        if params["healthcare_childcare"] and "childcare" in messages_text:
            recurring_factor = float(params["healthcare_childcare"])
    elif "transport" in context.expense_categories_to_protect:
        recurring_factor = max(recurring_factor, float(params["transport"]))

    if params["portfolio_mult"] and (
        "no units have been sold" in messages_text
        and "no cash proceeds" in messages_text
    ):
        recurring_factor *= float(params["portfolio_mult"])

    if "refund has been initiated" in messages_text and "not reached your account" in messages_text:
        all_factor = max(all_factor, float(params["refund_all"]))

    if "expected on" in messages_text and "payroll" in messages_text:
        recurring_factor = max(recurring_factor, float(params["payroll_date"]))

    if params["temporary_pay_mult"] and (
        "temporary monthly pay" in messages_text
        or "reduced amount continues" in messages_text
    ):
        recurring_factor *= float(params["temporary_pay_mult"])

    return _stress_debit_flows(
        flows,
        all_debits_factor=all_factor,
        recurring_debits_factor=recurring_factor,
    )


def _fmt_amount(v: float) -> str:
    return f"{v:.2f}"


def _compare(d: DecisionRow, labels: dict[str, str], tol: float = 1.0) -> dict[str, Any]:
    pred = {
        "request_id": d.request_id,
        "amount_safe_to_pay": _fmt_amount(d.amount_safe_to_pay),
        "affordability_status": d.affordability_status,
        "recommended_payment_method": d.recommended_payment_method,
        "payment_plan": d.payment_plan or "",
        "earliest_date_for_full_payment": d.earliest_date_for_full_payment or "",
        "spending_changes_needed": d.spending_changes_needed or "none",
    }
    mismatches: list[dict[str, str]] = []
    for field in COMPARE_FIELDS:
        p = (pred.get(field) or "").strip()
        g = (labels.get(field) or "").strip()
        if field == "amount_safe_to_pay":
            if not _amounts_close(p, g, tol):
                mismatches.append({"field": field, "predicted": p, "expected": g})
        elif p != g:
            mismatches.append({"field": field, "predicted": p, "expected": g})
    gold_amt = _parse_amount(labels.get("amount_safe_to_pay", "0"))
    amt_gap = abs(d.amount_safe_to_pay - gold_amt)
    non_amt = [m["field"] for m in mismatches if m["field"] != "amount_safe_to_pay"]
    return {
        "passed": len(mismatches) == 0,
        "mismatches": mismatches,
        "amount_gap": amt_gap,
        "non_amount_mismatch_fields": non_amt,
        "plan_match": pred.get("payment_plan", "") == (labels.get("payment_plan") or "").strip(),
        "status_match": pred.get("affordability_status") == (labels.get("affordability_status") or "").strip(),
    }


def _run_all(params: dict[str, float | None]) -> dict[str, DecisionRow]:
    def flows_fn(
        baseline_flows: list[dict[str, Any]],
        cash_events: list[ResolvedCashEvent],
        context: UserContextRow,
        spending_changes: str,
    ) -> list[dict[str, Any]]:
        return _amount_safe_flows_variant(
            baseline_flows, cash_events, context, spending_changes, params
        )

    decide_mod._amount_safe_flows = flows_fn  # type: ignore[method-assign]

    ledgers_path = _CODE / "temp_data" / "resolved_ledgers.json"
    ledgers = {
        x["user_id"]: x
        for x in json.loads(ledgers_path.read_text(encoding="utf-8"))["ledgers"]
    }
    out: dict[str, DecisionRow] = {}
    for ctx in load_user_context_rows():
        if ctx.data_source != "sample" or not ctx.sample_labels:
            continue
        ledger = ledgers[ctx.user_id]
        out[ctx.request_id] = decide_for_request(ctx, ledger)
    return out


def main() -> None:
    tuned = _run_all(TUNED)
    policy = _run_all(_policy_params_from_config())

    rows: list[dict[str, Any]] = []
    tuned_pass = policy_pass = 0
    tuned_closer = policy_closer = tie = 0
    plan_ok_both = plan_wrong_either = 0
    only_amount_tuned = only_amount_policy = 0

    for rid in sorted(tuned.keys()):
        labels = next(
            c.sample_labels
            for c in load_user_context_rows()
            if c.request_id == rid
        )
        assert labels
        ct = _compare(tuned[rid], labels)
        cp = _compare(policy[rid], labels)
        if ct["passed"]:
            tuned_pass += 1
        if cp["passed"]:
            policy_pass += 1

        if ct["amount_gap"] < cp["amount_gap"]:
            closer = "tuned"
            tuned_closer += 1
        elif cp["amount_gap"] < ct["amount_gap"]:
            closer = "policy"
            policy_closer += 1
        else:
            closer = "tie"
            tie += 1

        if ct["plan_match"] and cp["plan_match"]:
            plan_ok_both += 1
        if not ct["plan_match"] or not cp["plan_match"]:
            plan_wrong_either += 1

        if not ct["non_amount_mismatch_fields"] and ct["mismatches"]:
            only_amount_tuned += 1
        if not cp["non_amount_mismatch_fields"] and cp["mismatches"]:
            only_amount_policy += 1

        rows.append(
            {
                "request_id": rid,
                "tuned_pass": ct["passed"],
                "policy_pass": cp["passed"],
                "tuned_amount_gap": round(ct["amount_gap"], 2),
                "policy_amount_gap": round(cp["amount_gap"], 2),
                "amount_closer": closer,
                "tuned_non_amount": ct["non_amount_mismatch_fields"],
                "policy_non_amount": cp["non_amount_mismatch_fields"],
                "tuned_plan_ok": ct["plan_match"],
                "policy_plan_ok": cp["plan_match"],
                "gold_amount": labels.get("amount_safe_to_pay"),
                "tuned_amount": _fmt_amount(tuned[rid].amount_safe_to_pay),
                "policy_amount": _fmt_amount(policy[rid].amount_safe_to_pay),
            }
        )

    report = {
        "summary": {
            "tuned_full_pass": tuned_pass,
            "policy_full_pass": policy_pass,
            "total_sample": len(rows),
            "amount_gap_closer_tuned": tuned_closer,
            "amount_gap_closer_policy": policy_closer,
            "amount_gap_tie": tie,
            "payment_plan_matches_gold_both_policies": plan_ok_both,
            "payment_plan_wrong_at_least_one": plan_wrong_either,
            "failures_only_amount_tuned": only_amount_tuned,
            "failures_only_amount_policy": only_amount_policy,
        },
        "rows": rows,
    }

    out_path = _CODE / "temp_data" / "amount_safe_policy_comparison.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"-> {out_path}")


if __name__ == "__main__":
    main()
