# Stage 3 — Decisions, explanations, and submission output

## Purpose

Stage 3 combines each user's **request context** (Stage 1) with their **resolved ledger and forecast** (Stage 2) to produce affordability fields required by the challenge. It writes `output.csv` at the repository root and optionally compares sample predictions to gold labels.

LLM usage is limited to **`decision_explanation`**; all numeric and categorical decision fields are computed deterministically.

## Primary modules

| Module | Role |
|--------|------|
| `stage3/run.py` | Orchestration, CSV output, regression hook |
| `stage3/decide.py` | Core decision engine per request |
| `stage3/spending.py` | Apply / enumerate spending change strings |
| `stage3/plans.py` | Payment plan builders and formatting |
| `stage3/models.py` | `DecisionRow`, `CandidatePlan`, output columns |
| `stage3/explain.py` | LLM / stub / offline gold explanations |
| `stage3/regression.py` | Sample-only accuracy report |
| `llm/decision_explanation.py` | DeepSeek prompt for explanations |
| `llm/deepseek.py`, `llm/secrets.py`, `llm/usage.py` | API client and metering |

## Control flow

```
run_stage3(mode, regress_sample, use_llm_explanations, offline_sample_explanations)
    │
    ├─► reset_usage()
    │
    ├─► _ensure_ledgers(mode)
    │       if resolved_ledgers.json missing or wrong mode/count → run_stage2(mode)
    │
    ├─► _load_ledgers() → dict[user_id → ledger]
    ├─► load_user_context_rows() filtered by mode (sample/eval)
    │
    └─► for each context:
            │
            ├─► decide_for_request(context, ledger)
            │       │
            │       ├─ baseline_flows ← ledger.forecast.projected_flows
            │       ├─ cash_events ← ledger.cash_events
            │       │
            │       ├─ enumerate_spending_candidates() + "none"
            │       │
            │       ├─ per spending option:
            │       │     compute_amount_safe_to_pay()  [stressed flows, binary search]
            │       │     compute_reported_earliest_full_payment_date()
            │       │     _collect_candidates() → full / partial / installments / wait
            │       │     rank with _rank_key() → best CandidatePlan
            │       │
            │       └─► DecisionRow (or not_affordable fallback)
            │
            ├─► generate_decision_explanation(decision, context, ledger, ...)
            │       offline sample gold | stub | DeepSeek LLM | fallback stub
            │
            └─► decision.to_output_dict(explanation) → decisions_by_request
    │
    ├─► run_sample_regression() if regress_sample and sample rows exist
    │
    ├─► build out_rows:
    │       sample mode → all sample contexts in loader order
    │       else → eval request_ids from dataset/requests.csv order
    │
    ├─► _write_output_csv() → REPO_ROOT/output.csv
    └─► get_usage().write_json() when LLM explanations enabled
```

### CLI flags affecting Stage 3

| Flag | Effect |
|------|--------|
| `--no-regression` | Skip `regression_report.json` |
| `--stub-explanations` | Deterministic stub text (no API) |
| `--offline-explanations` | Sample users: gold `decision_explanation` from labels |

## Decision logic (summary)

### Amount safe to pay

`compute_amount_safe_to_pay` binary-searches the largest same-day payment that keeps balances ≥ minimum for 90 days when flows are:

1. Adjusted by `apply_spending_changes` (stop/reduce recurring series)
2. Deduped for salary credits per calendar month
3. **Stressed** via `_amount_safe_flows` using config multipliers (gig pending, salary ended, healthcare, refunds, etc.)

Planner safety checks (`_is_plan_safe`) use **unstressed** baseline flows + spending changes unless noted otherwise.

### Candidate plans

For each spending option, `_collect_candidates` may add:

- **Full payment** today (`affordable_now` or `affordable_with_plan`)
- **Partial payment** (safe amount today + remainder on earliest full date)
- **Installments** from payment options passing `installment_allowed`
- **Wait** until earliest full payment date within deadline

Plans are filtered with `is_balance_safe` and ranked by `_rank_key` (deadline met, prefer no spending changes, minimize pay, etc.).

### Output columns

Defined in `stage3/models.OUTPUT_COLUMNS`:

`request_id`, `amount_safe_to_pay`, `affordability_status`, `recommended_payment_method`, `payment_plan`, `earliest_date_for_full_payment`, `spending_changes_needed`, `decision_explanation`

## Regression (sample only)

`run_sample_regression` compares predicted fields to `sample_labels_json` for fields in `COMPARE_FIELDS` (tolerance on `amount_safe_to_pay`). Report: `code/temp_data/regression_report.json`.

Gold labels are **not** used inside `decide_for_request` — only for local evaluation and optional offline explanations.

## Outputs

- **`output.csv`** — submission-shaped rows (250 eval requests for `all`/`eval`)
- **`temp_data/regression_report.json`** — optional
- **`temp_data/llm_usage.json`** — optional token totals
