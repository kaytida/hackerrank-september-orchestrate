from __future__ import annotations

from stage2.events import resolve_cash_events
from stage2.forecast import build_ninety_day_forecast
from stage2.fx import ExchangeRateTable
from stage2.image_amounts import apply_image_amounts
from stage2.messages import apply_message_patches
from stage2.models import ResolvedLedger, UserContextRow


def build_resolved_ledger(
    context: UserContextRow,
    fx: ExchangeRateTable,
    image_lookup: dict[str, dict[str, str]],
) -> ResolvedLedger:
    events = apply_image_amounts(context.financial_events, image_lookup)
    events, patch_count = apply_message_patches(
        events, context.messages, context.request_date
    )
    cash_events, excluded = resolve_cash_events(events, context.home_currency, fx)

    image_patched_ids = [
        e["event_id"]
        for e in events
        if e.get("_amount_source") == "images_json"
    ]

    ledger = ResolvedLedger(
        user_id=context.user_id,
        request_id=context.request_id,
        request_date=context.request_date,
        home_currency=context.home_currency,
        starting_balance_home=context.current_available_balance,
        minimum_balance_to_keep=context.minimum_balance_to_keep,
        cash_events=cash_events,
        excluded_events=excluded,
        message_patch_count=patch_count,
        metadata={
            "data_source": context.data_source,
            "message_count": len(context.messages),
            "image_count": len(context.images),
            "payment_option_count": len(context.payment_options),
            "image_amount_patched_event_ids": image_patched_ids,
            "expense_categories_to_protect": list(
                context.expense_categories_to_protect
            ),
        },
    )
    ledger.forecast = build_ninety_day_forecast(ledger, context.messages)
    return ledger
