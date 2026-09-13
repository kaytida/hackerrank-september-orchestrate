# Buy or Wait? — Pipeline Documentation

This folder describes the three-stage pipeline for the **Buy or Wait?** HackerRank Orchestrate solution.

| Document | Scope |
|----------|--------|
| [stage1.md](stage1.md) | Data consolidation → `user_context.csv` |
| [stage2.md](stage2.md) | Ledger, FX, messages, **image amounts (LLM + saved)**, 90-day forecast |
| [stage3.md](stage3.md) | Deterministic decisions, **explanations (LLM + saved)**, `output.csv` |

Operational run commands and CLI tables live in **`code/README.md`**.

---

## End-to-end control flow

```
python code/main.py [--mode all|sample|eval] [flags]
        │
        ▼
   main()  ── parses CLI, selects full pipeline or single stage
        │
        ├── run_stage1()     → code/temp_data/user_context.csv
        │
        ├── run_stage2()     → code/temp_data/resolved_ledgers.json
        │       (DeepSeek on receipt images → images.json fallback)
        │
        └── run_stage3()     → output.csv (+ optional regression_report.json)
                (DeepSeek explanations → saved output fallback)
```

**Entry point:** `code/main.py`

- **`run_pipeline()`** runs Stages 1 → 2 → 3 when no `--stageN-only` flag is set.
- **`--stage1-only`**, **`--stage2-only`**, **`--stage3-only`** run one stage. Stage 3 may rebuild Stage 2 ledgers if `resolved_ledgers.json` is missing or its `mode` / `user_count` does not match.
- **`--mode`** scopes Stages 1–2 (`all` = 275 users, `sample` = 25, `eval` = 250). Stage 3 writes **250 eval rows** for `all` and `eval` (order from `dataset/requests.csv`); **25 rows** for `sample` mode.
- Explanation flags are documented below; they do **not** change affordability logic.

Shared paths and tuning constants: `code/config.py`.

---

## What is deterministic vs LLM-assisted

| Area | Deterministic | LLM (DeepSeek platform API) |
|------|----------------|-----------------------------|
| Affordability fields (`amount_safe_to_pay`, status, method, plan, dates, spending) | **Yes** — `stage3/decide.py` | No |
| `decision_explanation` | Fallback text only | **Primary** (default) |
| Blank event amounts from receipt images | Applied via lookup table | **Primary** per `dataset/images.csv` row |
| Message interpretation, forecast, FX | **Yes** | No |

Secrets: `DEEPSEEK_API_KEY` in environment or repo-root `.secrets.json`. See `code/llm/secrets.py` and `code/README.md`.

---

## Fallback strategy (images and explanations)

The pipeline is designed so a **normal run tries the API first**, and **pre-saved artifacts** keep runs working offline or on blocked networks.

### Images (Stage 2)

```
load_image_amount_lookup()
    │
    ├─► (1) build_image_lookup_via_llm(saved_lookup)   [llm/image_resolution.py]
    │       For each row in dataset/images.csv (16 images):
    │         PNG at dataset/media/images/<image_id>.png
    │         DeepSeek chat (+ vision payload when supported)
    │         → quick_lookup entry per related_event_id
    │       On per-image failure → use saved_lookup[event_id] if present
    │
    └─► (2) On total failure → return saved quick_lookup only
            from code/temp_data/images.json
```

`apply_image_amounts()` then fills blank `amount` on events from the lookup; patched events are tagged `_amount_source: images_json`. Forecast may use payslip amounts via `_image_salary_adjustments()` reading the same saved document summaries.

**Saved artifact:** `code/temp_data/images.json` with a `quick_lookup` map (`event_id` → `resolved_amount`, rationale, etc.). Hand-maintained backup when LLM or network is unavailable.

### Explanations (Stage 3)

```
generate_decision_explanation()
    │
    ├─► if --offline-explanations and sample gold label → use gold (sample users only)
    │
    ├─► if --stub-explanations (no LLM):
    │       saved explanation → sample gold → minimal fallback sentence
    │
    └─► else (default): try generate_llm_decision_explanation()  [llm/decision_explanation.py]
            on failure:
              saved explanation → sample gold → minimal fallback
```

**Saved artifacts (merged, `output.csv` wins on duplicate keys):**

1. Repo-root **`output.csv`** — `decision_explanation` column per `request_id`
2. **`code/temp_data/saved_decision_explanations.json`** — optional `{ "request_26": "...", ... }`

Loader: `llm/saved_results.py`. Cache is reset at the start of each Stage 3 run (`reset_explanations_cache()`).

The LLM prompt receives locked `final_decision` fields plus context (balances, messages, **image evidence summaries** from `images.json` via `image_evidence_for_request()`). It must not change decision fields.

---

## CLI flags (pipeline-wide)

| Flag | Effect |
|------|--------|
| `--mode all\|sample\|eval` | User scope for stages (default `all`) |
| `--stage1-only` / `--stage2-only` / `--stage3-only` | Run one stage |
| `--no-regression` | Skip `code/temp_data/regression_report.json` |
| `--stub-explanations` | Skip DeepSeek for explanations; use **saved** text |
| `--offline-explanations` | Sample users: gold `decision_explanation` from labels; disables LLM for entire Stage 3 (same as stub for `use_llm`) |

Token usage after a successful LLM explanation run: `code/temp_data/llm_usage.json`.

---

## Key artifacts

| Path | Stage | Purpose |
|------|-------|---------|
| `code/temp_data/user_context.csv` | 1 | Consolidated per-user input |
| `code/temp_data/images.json` | 2 | Saved image amount fallback + evidence summaries |
| `code/temp_data/resolved_ledgers.json` | 2 | Ledgers + 90-day forecast |
| `output.csv` | 3 | Submission + saved explanation fallback |
| `code/temp_data/regression_report.json` | 3 | Sample regression (optional) |
| `code/temp_data/llm_usage.json` | 3 | DeepSeek token totals (optional) |

---

## Module map (`code/llm/`)

| Module | Role |
|--------|------|
| `deepseek.py` | HTTP client → `https://api.deepseek.com/chat/completions` |
| `secrets.py` | `DEEPSEEK_API_KEY` from env or `.secrets.json` |
| `decision_explanation.py` | Build prompt, call API for one explanation |
| `image_resolution.py` | Per-receipt image amount extraction |
| `saved_results.py` | Load saved explanations from JSON + `output.csv` |
| `usage.py` | Aggregate tokens → `llm_usage.json` |
