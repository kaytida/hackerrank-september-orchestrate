"""Stage 2 entry: resolve ledgers and 90-day forecasts for all users in scope."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from config import RESOLVED_LEDGERS_FILENAME, TEMP_DATA_DIR, USER_CONTEXT_FILENAME
from stage2.context_loader import load_user_context_rows
from stage2.fx import ExchangeRateTable
from stage2.image_amounts import load_image_amount_lookup
from stage2.ledger import build_resolved_ledger

Mode = Literal["all", "sample", "eval"]


@dataclass(frozen=True)
class Stage2Result:
    """Metadata for resolved_ledgers.json written by Stage 2."""

    output_path: Path
    user_count: int
    mode: str


def _mode_to_data_source(mode: Mode) -> str | None:
    """Map pipeline mode to user_context data_source filter, or None for all users."""
    if mode == "all":
        return None
    if mode == "sample":
        return "sample"
    if mode == "eval":
        return "eval"
    raise ValueError(f"unknown mode: {mode}")


def run_stage2(
    mode: Mode = "all",
    user_context_path: Path | None = None,
    output_path: Path | None = None,
) -> Stage2Result:
    """Build resolved ledgers (with 90-day forecast) for each user and write JSON."""
    data_source = _mode_to_data_source(mode)
    contexts = load_user_context_rows(path=user_context_path, data_source=data_source)
    if not contexts:
        raise ValueError("No user_context rows to process for Stage 2.")

    fx = ExchangeRateTable.load()
    image_lookup = load_image_amount_lookup()

    ledgers = []
    for context in contexts:
        ledger_dict = build_resolved_ledger(context, fx, image_lookup).to_dict()
        ledgers.append(ledger_dict)
        if mode == "sample":
            forecast = ledger_dict.get("forecast") or {}
            first_below = forecast.get("first_below_minimum")
            if first_below:
                print(
                    f"  Forecast below minimum: {context.request_id} "
                    f"first_breach={first_below.get('date')} "
                    f"balance_end={first_below.get('balance_end')} "
                    f"min={first_below.get('minimum_balance_required')}"
                )

    out = output_path or (TEMP_DATA_DIR / RESOLVED_LEDGERS_FILENAME)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "source_user_context": str(user_context_path or (TEMP_DATA_DIR / USER_CONTEXT_FILENAME)),
        "mode": mode,
        "user_count": len(ledgers),
        "ledgers": ledgers,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return Stage2Result(output_path=out, user_count=len(ledgers), mode=mode)
