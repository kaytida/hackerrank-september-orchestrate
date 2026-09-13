# Stage 2 — Resolved ledger and 90-day forecast

## Purpose

Stage 2 turns each `UserContextRow` into a **resolved ledger**: cash events in home currency, exclusions with reasons, message-driven patches, and a **90-day daily balance forecast** from `request_date` (without request payments). Results are stored in `code/temp_data/resolved_ledgers.json` for Stage 3.

## Primary modules

| Module | Role |
|--------|------|
| `stage2/run.py` | Orchestrates load → ledger per user → JSON write |
| `stage2/context_loader.py` | CSV → `UserContextRow` |
| `stage2/ledger.py` | Single-user pipeline: images → messages → resolve → forecast |
| `stage2/image_amounts.py` | Fill blank amounts from `temp_data/images.json` |
| `stage2/messages.py` | Apply `EventPatch` list to raw events |
| `stage2/message_rules.py` | Parse messages → patches + forecast adjustments |
| `stage2/message_forecast.py` | Apply adjustments to projected flows |
| `stage2/events.py` | Filter, FX convert, supersession logic |
| `stage2/fx.py` | Dated exchange rates |
| `stage2/recurrence.py` | Detect recurring spend/income from history |
| `stage2/forecast.py` | Known future + recurring flows, simulate balances |
| `stage2/protected_forecast.py` | Optional protected-category monthly floors (utility) |
| `stage2/models.py` | `UserContextRow`, `ResolvedCashEvent`, `ResolvedLedger` |

## Control flow

```
run_stage2(mode)
    │
    ├─► _mode_to_data_source(mode) → filter CSV rows (optional)
    │
    ├─► load_user_context_rows(data_source=...)
    │
    ├─► ExchangeRateTable.load()     ← dataset/exchange_rates.csv
    ├─► load_image_amount_lookup()   ← temp_data/images.json quick_lookup
    │
    └─► for each context:
            build_resolved_ledger(context, fx, image_lookup)
                │
                ├─► apply_image_amounts(events, lookup)
                │       blank amounts → resolved_amount from lookup
                │
                ├─► apply_message_patches(events, messages, request_date)
                │       interpret_messages() → EventPatch[]
                │       cancel / reschedule salary / cancel bonus, etc.
                │
                ├─► resolve_cash_events(events, home_currency, fx)
                │       exclude non-cash, pending credits, failed, etc.
                │       convert amounts to home currency
                │       drop superseded linked events
                │
                ├─► ResolvedLedger(...) + metadata
                │
                └─► build_ninety_day_forecast(ledger, messages)
                        │
                        ├─► _collect_known_future_flows()
                        │       scheduled + pending debits on/after request_date
                        │
                        ├─► _collect_recurrence_flows()
                        │       detect_recurrence_series() on settled history
                        │       project forward; skip salary if final payroll ended
                        │
                        ├─► get_message_forecast_adjustments()
                        │       + _image_salary_adjustments() from images.json
                        │
                        ├─► apply_forecast_adjustments()
                        │       cancel credits, override salary, rent scale, etc.
                        │
                        └─► _simulate_daily_balances() → forecast dict
            ledger.to_dict() appended to ledgers[]
    │
    └─► write resolved_ledgers.json (schema_version, mode, user_count, ledgers)
```

### Invocation

- Full pipeline: Stage 1 then `run_stage2(mode)` from `main.run_pipeline()`.
- Stage 3 calls `_ensure_ledgers()` which reuses cached JSON when `mode` and `user_count` match expectations; otherwise runs `run_stage2(mode)` again.

## Ledger resolution rules (summary)

**Excluded from cash ledger** (`events.py`):

- Unrealized investments, non-cash direction, failed/cancelled
- Pending **credits** (debits may remain for forecast)
- Missing amount/date or FX failure
- Parent events superseded by later linked settled/cancelled/failed child

**Message patches** (`message_rules.py` + `messages.py`):

- Event-level: cancel related unsettled credit, cancel future bonuses, reschedule salary settlement dates
- Forecast-level: separate list applied in `message_forecast.apply_forecast_adjustments`

## Forecast model

1. **Baseline flows** = known future + recurring projections (no payment plan).
2. **Occupancy rules** avoid double-counting the same recurrence key or category/direction/date slot.
3. **Daily simulation** applies debits before credits each day; tracks `below_minimum` vs `minimum_balance_to_keep`.
4. **Exported helpers** used by Stage 3:
   - `is_balance_safe()` — 90-day check with optional extra payment flows
   - `payment_flows()` — turn plan tuples into debit flows

Forecast payload on each ledger includes `projected_flows`, `daily_balances`, `first_below_minimum`, counts, etc.

## Outputs

- **File:** `code/temp_data/resolved_ledgers.json`
- **Return type:** `Stage2Result(output_path, user_count, mode)`

## Downstream (Stage 3)

Stage 3 loads ledgers by `user_id`, reads `forecast.projected_flows` as the **baseline** for affordability simulation, and rehydrates `ResolvedCashEvent` lists from `cash_events` for spending-change logic.
