# Stage 1 — User context consolidation

## Purpose

Stage 1 reads scattered CSV files under `dataset/` and produces **one row per user** in `code/temp_data/user_context.csv`. Each row joins profile, request, payment options, events, messages, images, and (for sample users) gold labels into scalar columns plus JSON blob columns for nested data.

Downstream stages never read the raw dataset CSVs directly; they load `UserContextRow` objects from this file.

## Primary modules

| Module | Role |
|--------|------|
| `stage1/consolidate.py` | Build rows, validate, write CSV |
| `stage1/__init__.py` | Exports `run_stage1` |
| `config.py` | Paths, column lists, `TEMP_DATA_DIR` |

## Control flow

```
run_stage1(mode)
    │
    ├─► build_user_context_rows(mode)
    │       │
    │       ├─► _read_csv() on financial_profiles, financial_events, messages,
    │       │   images, request_payment_options
    │       │
    │       ├─► _build_request_maps()
    │       │       merges requests.csv (eval) + sample_requests.csv (sample)
    │       │       → requests_by_user, sample_by_user, data_source per user
    │       │
    │       ├─► _select_users(source, mode)  → user list (all / sample / eval)
    │       │
    │       ├─► _enrich_images() per user (path + file_exists flag)
    │       │
    │       ├─► _validate_referential_integrity()
    │       │       profiles, requests, events, payment option counts,
    │       │       image↔event links, blank amounts without images
    │       │
    │       └─► assemble each output row (scalars + JSON columns)
    │
    └─► write_user_context_csv(rows) → user_context.csv
            returns ConsolidationResult(output_path, row_count, mode)
```

### Invocation from the CLI

- `python code/main.py` → `run_pipeline()` → `run_stage1(mode)` first.
- `python code/main.py --stage1-only --mode sample` → only Stage 1.

## Data shape

**Scalar columns:** `user_id`, `request_id`, `data_source`, profile fields, request fields (from `PROFILE_COLUMNS` and `REQUEST_INPUT_COLUMNS` in config).

**JSON columns:**

- `payment_options_json` — 2–4 options per request
- `financial_events_json` — ledger source events
- `messages_json` — untrusted narrative updates
- `images_json` — metadata + `image_path` / `image_file_present`
- `sample_labels_json` — gold outputs for sample users only (`null` for eval)

## Mode behavior

| `mode` | Users included |
|--------|----------------|
| `all` | All sample + eval users (275) |
| `sample` | `data_source == "sample"` (25) |
| `eval` | `data_source == "eval"` (250) |

Users are sorted by numeric suffix in `user_NNN`.

## Validation (fail-fast)

`_validate_referential_integrity` raises `ValueError` if:

- Missing profile, request, or events for a selected user
- Payment options count not in 2–4
- Image references unknown event or missing PNG on disk
- Settled-path event has blank `amount` and no linked image

## Outputs

- **File:** `code/temp_data/user_context.csv`
- **Return type:** `ConsolidationResult` with path, row count, and mode

## Images (metadata only in Stage 1)

Stage 1 does **not** OCR images or call DeepSeek. It:

- Joins rows from `dataset/images.csv` into `images_json`
- Sets `image_path` and `image_file_present` for each PNG under `dataset/media/images/`
- Validates `related_event_id` links and blank amounts that require an image link

**Amount extraction** happens in Stage 2: DeepSeek per receipt image, with fallback to `code/temp_data/images.json`. See [stage2.md](stage2.md).

## Downstream consumers

- **Stage 2:** `stage2/context_loader.load_user_context_rows()` reads the CSV.
- **Stage 3:** Same loader for request metadata; decisions use ledgers from Stage 2.
