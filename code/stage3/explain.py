"""Decision explanations (OpenRouter LLM with deterministic fallback)."""

from __future__ import annotations

import sys
from typing import Any

from stage2.models import UserContextRow
from stage3.models import DecisionRow

_llm_warned = False


def _stub_explanation(decision: DecisionRow, home_currency: str) -> str:
    method = decision.recommended_payment_method
    status = decision.affordability_status
    amount = decision.amount_safe_to_pay
    return (
        f"{status.replace('_', ' ').title()} via {method}; safe to pay {amount} "
        f"{home_currency} on {decision.request_id}. "
        f"Plan: {decision.payment_plan or 'none'}."
    )


def _sample_gold_explanation(context: UserContextRow) -> str | None:
    labels = context.sample_labels or {}
    text = (labels.get("decision_explanation") or "").strip()
    return text or None


def generate_decision_explanation(
    decision: DecisionRow,
    context: UserContextRow,
    ledger: dict[str, Any] | None = None,
    *,
    use_llm: bool = True,
    offline_sample_explanations: bool = False,
) -> str:
    gold = _sample_gold_explanation(context) if context.data_source == "sample" else None

    if offline_sample_explanations and gold:
        return gold

    if not use_llm:
        return gold or _stub_explanation(decision, context.home_currency)

    try:
        from llm.decision_explanation import generate_llm_decision_explanation

        return generate_llm_decision_explanation(context, decision, ledger)
    except Exception as exc:
        from llm.usage import get_usage

        get_usage().record_failure()
        global _llm_warned
        if not _llm_warned:
            print(
                f"Warning: LLM explanation failed ({exc}); using stub for this run.",
                file=sys.stderr,
            )
            _llm_warned = True
        return gold or _stub_explanation(decision, context.home_currency)
