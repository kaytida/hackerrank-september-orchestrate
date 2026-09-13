# Buy or Wait? — Pipeline Documentation

This folder describes the three-stage pipeline that powers the **Buy or Wait?** Hackerrank Orchestrate solution.

| Document | Scope |
|----------|--------|
| [stage1.md](stage1.md) | Data consolidation → `user_context.csv` |
| [stage2.md](stage2.md) | Ledger resolution, FX, messages, 90-day forecast |
| [stage3.md](stage3.md) | Affordability decisions, explanations, `output.csv` |

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
        │
        └── run_stage3()     → output.csv (+ optional regression_report.json)
```

**Entry point:** `code/main.py`

- **`run_pipeline()`** runs stages 1 → 2 → 3 in order when no `--stageN-only` flag is set.
- **`--stage1-only`**, **`--stage2-only`**, **`--stage3-only`** run a single stage (Stage 3 may rebuild Stage 2 ledgers if cache is missing or stale).
- **`--mode`** limits which users are processed in Stages 1–2; Stage 3 still writes eval `request_id` order for `all` and `eval` modes.
- **`--stub-explanations`** / **`--offline-explanations`** control how `decision_explanation` is produced in Stage 3.

Shared paths and tuning constants live in `code/config.py`.
