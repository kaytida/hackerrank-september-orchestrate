"""Decision explanations (DeepSeek LLM with saved-result fallback)."""

from __future__ import annotations

import sys
from typing import Any

from llm.saved_results import get_saved_explanation
from stage2.models import UserContextRow
from stage3.models import DecisionRow

_llm_warned = False
_saved_warned = False


def _minimal_fallback(decision: DecisionRow, home_currency: str) -> str:
    """Last resort when LLM and saved explanations are unavailable."""
    return (
        f"{decision.affordability_status.replace('_', ' ').title()} via "
        f"{decision.recommended_payment_method}; safe to pay "
        f"{decision.amount_safe_to_pay} {home_currency}."
    )


def _sample_gold_explanation(context: UserContextRow) -> str | None:
    """Return gold decision_explanation from sample labels when present."""
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
    """Produce decision_explanation: LLM first, then saved output, then sample gold."""
    gold = _sample_gold_explanation(context) if context.data_source == "sample" else None

    if offline_sample_explanations and gold:
        return gold

    if not use_llm:
        saved = get_saved_explanation(context.request_id)
        return saved or gold or _minimal_fallback(decision, context.home_currency)

    try:
        from llm.decision_explanation import generate_llm_decision_explanation

        return generate_llm_decision_explanation(context, decision, ledger)
    except Exception as exc:
        from llm.usage import get_usage

        get_usage().record_failure()
        global _llm_warned, _saved_warned
        if not _llm_warned:
            print(
                f"Warning: LLM explanation failed ({exc}); using saved explanations.",
                file=sys.stderr,
            )
            _llm_warned = True
        saved = get_saved_explanation(context.request_id)
        if saved:
            return saved
        if not _saved_warned:
            print(
                "Warning: No saved explanation for "
                f"{context.request_id}; using minimal fallback.",
                file=sys.stderr,
            )
            _saved_warned = True
        return gold or _minimal_fallback(decision, context.home_currency)
