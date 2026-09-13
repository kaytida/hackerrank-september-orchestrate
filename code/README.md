# Buy or Wait? — Code Runner

Python pipeline that reads `dataset/` and writes **`output.csv`** at the repository root (submission file).

**Working directory:** run commands from the **repository root** (`hackerrank-orchestrate-september26/`), not from `code/`.

```bash
python code/main.py [options]
```

Show all flags:

```bash
python code/main.py --help
```

---

## Quick start — generate submission `output.csv`

For the HackerRank eval set (**250 rows**, one per row in `dataset/requests.csv`):

```bash
python code/main.py
```

Same as `python code/main.py --mode all`: runs Stage 1 → 2 → 3, then writes `output.csv` next to `dataset/`.

**Without DeepSeek** (deterministic stub text in `decision_explanation`; no API key):

```bash
python code/main.py --stub-explanations
```

**With LLM explanations** (default): set `DEEPSEEK_API_KEY` in the environment or in repo-root `.secrets.json` (see [Secrets](#secrets-for-llm-explanations)).

On success you should see paths printed for intermediate files and a line like `Wrote 250 rows -> .../output.csv`.

---

## Prerequisites

- Python **3.10+** (3.12 tested)
- Unmodified challenge data under `dataset/`
- `code/temp_data/images.json` — hand-extracted image amounts (vision API not required)

**Stage order:** Stage 3 needs `code/temp_data/user_context.csv` (Stage 1). It rebuilds `code/temp_data/resolved_ledgers.json` via Stage 2 automatically if that file is missing or its stored `mode` / `user_count` does not match the current `--mode`.

---

## CLI options (complete)

| Flag | Default | Description |
|------|---------|-------------|
| *(no stage flags)* | — | Run **Stage 1 → 2 → 3** in one process |
| `--mode all` | **yes** (`all`) | Stages 1–2: **275** users (25 sample + 250 eval). Stage 3: writes **250** eval rows to `output.csv` (sample users still processed for regression context). |
| `--mode sample` | — | **25** sample users only (`sample_requests.csv`). Stage 3 writes **25** rows to `output.csv`. |
| `--mode eval` | — | **250** eval users only (`requests.csv`). Stage 3 writes **250** rows to `output.csv`. |
| `--stage1-only` | off | Consolidation only → `code/temp_data/user_context.csv` |
| `--stage2-only` | off | Ledger + 90-day forecast → `code/temp_data/resolved_ledgers.json` |
| `--stage3-only` | off | Decisions + `output.csv` (+ optional regression) |
| `--no-regression` | off | Do not write `code/temp_data/regression_report.json` in Stage 3 |
| `--stub-explanations` | off | Skip DeepSeek; use deterministic explanation stubs |
| `--offline-explanations` | off | For **sample** users only, copy gold `decision_explanation` from labels (no API). Eval rows still use LLM unless `--stub-explanations` is also set |

**Constraints**

- Use **at most one** of `--stage1-only`, `--stage2-only`, `--stage3-only`.
- `--mode` applies to whichever stage(s) you run.

**Combining flags (examples)**

| Goal | Command |
|------|---------|
| Full submission pipeline | `python code/main.py` |
| Full pipeline, no API | `python code/main.py --stub-explanations` |
| Regenerate predictions only | `python code/main.py --stage3-only --mode all` |
| Fast sample calibration (25-row output) | `python code/main.py --mode sample` |
| Stage 3 sample, no regression file | `python code/main.py --stage3-only --mode sample --no-regression` |
| Eval users in intermediates only | `python code/main.py --stage1-only --mode eval` then stage 2/3 with `--mode eval` |

---

## How `--mode` affects `output.csv`

| `--mode` | Rows in `output.csv` | `request_id` source |
|----------|----------------------|---------------------|
| `all` | **250** | `dataset/requests.csv` (eval order) |
| `eval` | **250** | `dataset/requests.csv` |
| `sample` | **25** | Sample users in consolidated context (`request_01` … `request_25`) |

Upload **`--mode all`** (or default) output for the contest: **250 data rows + header**, columns in challenge order.

---

## Secrets for LLM explanations

Stage 3 calls the **DeepSeek platform API** (`https://api.deepseek.com/chat/completions`, model `deepseek-chat`) for `decision_explanation` when neither `--stub-explanations` nor `--offline-explanations` is set.

1. **Environment:** `DEEPSEEK_API_KEY=...`
2. **Or** repo-root `.secrets.json` (gitignored):

```json
{
  "DEEPSEEK_API_KEY": "sk-..."
}
```

(Also accepts `deepseek_api_key` or `deepseek` as the JSON key name.)

Run on a network that can reach `api.deepseek.com`. Smoke test:

```bash
python code/test_deepseek.py
```

If the API is unreachable (e.g. corporate firewall), use `--stub-explanations` or `--offline-explanations` instead of changing the client.

After an LLM run, token usage is written under `code/temp_data/` (see printed `LLM usage -> ...` line).

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

Affordability and payment fields are **deterministic** (Stages 2–3 planner). Only `decision_explanation` is LLM-generated unless you pass `--stub-explanations` or `--offline-explanations` for sample rows.

---

## Regression testing (25 sample requests)

Gold labels are in `user_context.csv` (`sample_labels_json`) for `data_source=sample` users.

Regression runs when Stage 3 processes at least one sample user and `--no-regression` is **not** set. Compared fields (default **±1** tolerance on `amount_safe_to_pay`):

- `amount_safe_to_pay`, `affordability_status`, `recommended_payment_method`, `payment_plan`, `earliest_date_for_full_payment`, `spending_changes_needed`

Report: `code/temp_data/regression_report.json` (`passed`, `failed`, `pass_rate`, per-request `mismatches`).

**Fast loop after changing Stage 2/3 logic:**

```bash
python code/main.py --stage1-only --mode sample
python code/main.py --stage2-only --mode sample
python code/main.py --stage3-only --mode sample
```

**Full 275-user context, still score 25 samples:**

```bash
python code/main.py --stage1-only --mode all
python code/main.py --stage2-only --mode all
python code/main.py --stage3-only --mode all
```

Stage 3 with `--mode all` still writes **250** eval rows to `output.csv` while regression uses the 25 sample predictions from the same run.

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
3. **Stage 3** — Deterministic affordability + explanation (DeepSeek or stubs) → `output.csv` + optional `regression_report.json`

Exchange rates are always read from `dataset/exchange_rates.csv` (not copied into `user_context.csv`).

Deeper control-flow notes: `docs/stage1.md`, `docs/stage2.md`, `docs/stage3.md` at repo root.

---

## Quick checklist before upload

- [ ] `python code/main.py` completed without errors
- [ ] `output.csv` has **250** data rows + header
- [ ] Column names and order match the challenge spec
- [ ] `code/temp_data/regression_report.json` reviewed if you rely on sample pass rate
- [ ] Explanation mode documented (`--stub-explanations` vs live DeepSeek) for your submission package
