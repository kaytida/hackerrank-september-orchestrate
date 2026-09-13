# Buy or Wait? — Code Runner

Entry point: `main.py` (run from the repository root unless noted).

```bash
python code/main.py [options]
```

All paths below are relative to the **repository root** (`hackerrank-orchestrate-september26/`).

---

## Prerequisites

- Python 3.10+ (3.12 tested)
- Dataset unchanged under `dataset/` (read-only inputs)
- `code/temp_data/images.json` — hand-extracted image amounts (no vision LLM required)

Stage 3 reads `code/temp_data/user_context.csv`. If it is missing, run Stage 1 first. Stage 3 rebuilds `code/temp_data/resolved_ledgers.json` automatically when the file is missing or its `mode` / `user_count` does not match the current `--mode`.

---

## CLI reference

| Flag | Description |
|------|-------------|
| *(none)* | Run **Stage 1 → 2 → 3** with `--mode all` |
| `--mode all` | 275 users (25 sample + 250 eval) in Stages 1–2; Stage 3 uses all contexts for decisions where needed |
| `--mode sample` | 25 public sample users only (`sample_requests.csv`) |
| `--mode eval` | 250 held-out eval users only (`requests.csv`) |
| `--stage1-only` | Consolidation only → `code/temp_data/user_context.csv` |
| `--stage2-only` | Ledger + 90-day forecast → `code/temp_data/resolved_ledgers.json` |
| `--stage3-only` | Decisions + `output.csv` (+ regression when applicable) |
| `--no-regression` | Skip writing `code/temp_data/regression_report.json` in Stage 3 |

Only one of `--stage1-only`, `--stage2-only`, `--stage3-only` may be used at a time.

---

## Artifacts

| File | Produced by | Purpose |
|------|-------------|---------|
| `code/temp_data/user_context.csv` | Stage 1 | One row per user; JSON columns for events, messages, payment options, sample labels |
| `code/temp_data/resolved_ledgers.json` | Stage 2 | Resolved cash events + `forecast` (90-day baseline) per user |
| `code/temp_data/regression_report.json` | Stage 3 | Sample vs gold field mismatches (when regression runs) |
| `output.csv` | Stage 3 | **Submission file** (repo root) |

`output.csv` columns (in order):  
`request_id`, `amount_safe_to_pay`, `affordability_status`, `recommended_payment_method`, `payment_plan`, `earliest_date_for_full_payment`, `spending_changes_needed`, `decision_explanation`

`decision_explanation` uses **OpenRouter** by default (`code/llm/`); pass `--stub-explanations` to skip API calls.

---

## Regression testing (25 sample requests)

Sample gold labels live in `user_context.csv` (`sample_labels_json`) for `data_source=sample` users (`request_01` … `request_25`).

Regression runs when Stage 3 processes at least one sample user and `--no-regression` is **not** set. It compares these fields to gold (default **±1** tolerance on `amount_safe_to_pay`):

- `amount_safe_to_pay`
- `affordability_status`
- `recommended_payment_method`
- `payment_plan`
- `earliest_date_for_full_payment`
- `spending_changes_needed`

Results: `code/temp_data/regression_report.json` (`passed`, `failed`, `pass_rate`, per-request `mismatches`).

### Recommended regression workflow

**Fast loop (sample only, after changing Stage 2/3 logic):**

```bash
python code/main.py --stage1-only --mode sample
python code/main.py --stage2-only --mode sample
python code/main.py --stage3-only --mode sample
```

- Writes **`output.csv` with 25 rows** (sample requests only).
- Prints e.g. `Sample regression: X/25 passed -> code/temp_data/regression_report.json`.

**Full-context decisions, sample regression only:**

```bash
python code/main.py --stage1-only --mode all
python code/main.py --stage2-only --mode all
python code/main.py --stage3-only --mode all
```

- Processes **275** users in Stages 1–2.
- Stage 3 still runs regression on the **25** sample predictions embedded in the full run.
- Writes **`output.csv` with 250 rows** (eval / submission set).

**Regression without rewriting submission output shape (sample output file):**

Use `--mode sample` for all three stages when you only want a 25-row `output.csv` and the report.

**Skip regression (faster, no report file):**

```bash
python code/main.py --stage3-only --mode sample --no-regression
```

**Inspect failures:** open `code/temp_data/regression_report.json` and fix Stage 2 forecast rules or Stage 3 planner; re-run Stage 2–3 (or Stage 3 only if ledgers still match `--mode`).

---

## Eval output (250 requests — submission)

Official eval requests are in `dataset/requests.csv` (`request_26` …, 250 rows). They are **not** in `sample_requests.csv`.

### Produce submission `output.csv` (250 rows)

**One-shot full pipeline (recommended before submit):**

```bash
python code/main.py
```

Equivalent to:

```bash
python code/main.py --mode all
```

This runs Stages 1–3 with `mode=all`, writes **`output.csv`** at the repo root with **250** rows (eval `request_id` order from `dataset/requests.csv`), and runs sample regression if sample users were included in the run.

**Eval-only scope (250 users in intermediate files):**

```bash
python code/main.py --stage1-only --mode eval
python code/main.py --stage2-only --mode eval
python code/main.py --stage3-only --mode eval
```

Requires `user_context.csv` to contain eval users (run Stage 1 with `--mode all` or `--mode eval` after a full consolidation). Stage 3 with `--mode eval` writes **250** rows to `output.csv`.

**Stage 3 only (ledgers rebuilt if needed):**

```bash
python code/main.py --stage3-only --mode all
```

Uses existing `user_context.csv` (must cover all **250** eval users). Rebuilds `resolved_ledgers.json` if its stored `mode`/`user_count` ≠ `all`/275.

### What `output.csv` is *not*

- `--mode sample` → **25** rows (for calibration, not HackerRank eval upload).
- Regression report does not replace `output.csv`; it only scores sample rows when sample users are processed in Stage 3.

---

## Stage-by-stage (debugging)

| Goal | Command |
|------|---------|
| Refresh consolidated input | `python code/main.py --stage1-only --mode all` |
| Refresh ledgers + forecast | `python code/main.py --stage2-only --mode all` |
| Regenerate predictions only | `python code/main.py --stage3-only --mode all` |

---

## Pipeline stages (summary)

1. **Stage 1** — Join `dataset/*` → `code/temp_data/user_context.csv`
2. **Stage 2** — Ledger, `images.json` amounts, FX, 90-day baseline forecast → `resolved_ledgers.json`
3. **Stage 3** — Deterministic affordability + stub explanation → `output.csv` + optional `regression_report.json`

Exchange rates: always read from `dataset/exchange_rates.csv` (not copied into `user_context.csv`).

Message and vision LLM hooks are stubbed; the pipeline runs without API keys.

---

## Quick checklist before upload

- [ ] `python code/main.py` completed without errors
- [ ] `output.csv` has **250** data rows + header
- [ ] Column names and order match the challenge spec
- [ ] `code/temp_data/regression_report.json` reviewed (sample pass rate acceptable for your iteration)
- [ ] `decision_explanation` still stubbed unless LLM step was added
