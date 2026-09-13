# Stage 3 — Decisions, explanations, and submission output

## Purpose

Stage 3 combines each user's **request context** (Stage 1) with their **resolved ledger and forecast** (Stage 2) to produce affordability fields required by the challenge. It writes `output.csv` at the repository root and optionally compares sample predictions to gold labels.

**Affordability fields are always deterministic.** Only **`decision_explanation`** uses DeepSeek, with **saved text** as fallback.

## Primary modules

| Module | Role |
|--------|------|
| `stage3/run.py` | Orchestration, CSV output, regression hook |
| `stage3/decide.py` | Core decision engine per request |
| `stage3/spending.py` | Apply / enumerate spending change strings |
| `stage3/plans.py` | Payment plan builders and formatting |
| `stage3/models.py` | `DecisionRow`, `CandidatePlan`, output columns |
| `stage3/explain.py` | **LLM → saved → gold → minimal** explanation chain |
| `stage3/regression.py` | Sample-only accuracy report |
| `llm/decision_explanation.py` | DeepSeek prompt for explanations |
| `llm/deepseek.py` | Platform API client |
| `llm/secrets.py` | API key loading |
| `llm/saved_results.py` | Read saved explanations |
| `llm/usage.py` | Token metering → `llm_usage.json` |

## Control flow

```
run_stage3(mode, regress_sample, use_llm_explanations, offline_sample_explanations)
    │
    ├─► reset_usage()
    ├─► reset_explanations_cache()
    │
    ├─► _ensure_ledgers(mode)
    │       if resolved_ledgers.json missing or wrong mode/count → run_stage2(mode)
    │
    ├─► _load_ledgers() → dict[user_id → ledger]
    ├─► load_user_context_rows() filtered by mode (sample/eval)
    │
    └─► for each context:
            │
            ├─► decide_for_request(context, ledger)     [always deterministic]
            │       baseline_flows, spending candidates, plan ranking → DecisionRow
            │
            ├─► generate_decision_explanation(...)    [see diagram below]
            │
            └─► decision.to_output_dict(explanation) → decisions_by_request
    │
    ├─► run_sample_regression() if regress_sample and sample rows exist
    │
    ├─► build out_rows (sample order vs dataset/requests.csv eval order)
    ├─► _write_output_csv() → REPO_ROOT/output.csv
    └─► get_usage().write_json() when LLM explanations enabled and not offline-only
```

### Explanation resolution (LLM + fallbacks)

```
generate_decision_explanation(decision, context, ledger, use_llm, offline_sample_explanations)
    │
    ├─► gold ← sample_labels.decision_explanation (sample users only)
    │
    ├─► if offline_sample_explanations and gold:
    │       return gold
    │
    ├─► if not use_llm:                    # --stub-explanations or --offline-explanations
    │       return get_saved_explanation(request_id)
    │           or gold
    │           or _minimal_fallback(...)
    │
    └─► else (default run):
            try generate_llm_decision_explanation(context, decision, ledger)
                │  payload: request, messages, image_evidence, locked final_decision
                │  API: llm/deepseek.py (model deepseek-chat)
            except:
                return get_saved_explanation(request_id)
                    or gold
                    or _minimal_fallback(...)
```

**Saved explanations** (`llm/saved_results.py`):

| Source | Path |
|--------|------|
| Optional JSON cache | `code/temp_data/saved_decision_explanations.json` |
| Submission / last good run | Repo-root `output.csv` (`decision_explanation` column) |

Merged map is built once per Stage 3 run; **`output.csv` overwrites** the same `request_id` in the JSON file.

**Minimal fallback:** one short sentence with status, method, and `amount_safe_to_pay` — only when LLM and saved text are both missing.

### CLI flags affecting Stage 3

| Flag | `use_llm` | Explanation behavior |
|------|-----------|----------------------|
| *(default)* | true | DeepSeek per row; on API error → saved → gold → minimal |
| `--stub-explanations` | false | Saved → gold → minimal (no API) |
| `--offline-explanations` | false | Sample rows: gold first when flag set at start; same as stub for API |
| `--no-regression` | — | Skip `regression_report.json` only |

`main.py` sets `use_llm = not stub_explanations and not offline_explanations`.

---

## Decision logic (summary)

### Amount safe to pay

`compute_amount_safe_to_pay` binary-searches the largest same-day payment that keeps balances ≥ minimum for 90 days when flows are stressed per `code/config.py` multipliers.

### Candidate plans

Full / partial / installments / wait plans are ranked with `is_balance_safe` and `_rank_key`.

### Output columns

`request_id`, `amount_safe_to_pay`, `affordability_status`, `recommended_payment_method`, `payment_plan`, `earliest_date_for_full_payment`, `spending_changes_needed`, `decision_explanation`

---

## Regression (sample only)

`run_sample_regression` compares predicted fields to `sample_labels_json` (`COMPARE_FIELDS`). Report: `code/temp_data/regression_report.json`.

Gold labels are **not** used inside `decide_for_request` except when `--offline-explanations` is set for explanation text on sample users.

---

## Outputs

| File | Notes |
|------|--------|
| `output.csv` | Submission file; also feeds saved-explanation fallback |
| `code/temp_data/regression_report.json` | Optional sample pass/fail |
| `code/temp_data/llm_usage.json` | Optional DeepSeek usage summary |

---

## Style note for `decision_explanation`

Public sample text in `dataset/sample_requests.csv` uses short, user-facing sentences (amounts, dates, minimum balance). The LLM system prompt in `llm/decision_explanation.py` instructs that style. When using **`--stub-explanations`**, prefer maintaining repo-root `output.csv` with finalized explanations so fallbacks match that style without calling the API.
