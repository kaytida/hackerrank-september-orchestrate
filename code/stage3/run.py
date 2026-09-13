"""Stage 3 entry: affordability decisions, explanations, and output.csv."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from config import DATASET_DIR, REPO_ROOT, RESOLVED_LEDGERS_FILENAME, TEMP_DATA_DIR
from stage2.context_loader import load_user_context_rows
from stage2.run import run_stage2
from stage3.decide import decide_for_request
from llm.saved_results import reset_explanations_cache
from llm.usage import get_usage, reset_usage
from stage3.explain import generate_decision_explanation
from stage3.models import OUTPUT_COLUMNS
from stage3.regression import run_sample_regression

Mode = Literal["all", "sample", "eval"]


@dataclass(frozen=True)
class Stage3Result:
    """Summary after writing output.csv and optional regression message."""

    output_path: Path
    row_count: int
    regression: str | None


def _load_ledgers(path: Path) -> dict[str, dict]:
    """Index resolved ledgers by user_id from Stage 2 JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {ledger["user_id"]: ledger for ledger in data.get("ledgers", [])}


def _expected_user_count(mode: Mode) -> int:
    """Expected ledger count for cache validation before Stage 3."""
    return {"all": 275, "sample": 25, "eval": 250}[mode]


def _ensure_ledgers(mode: Mode) -> Path:
    """Return path to resolved_ledgers.json, rebuilding via Stage 2 if cache is stale."""
    ledger_path = TEMP_DATA_DIR / RESOLVED_LEDGERS_FILENAME
    expected = _expected_user_count(mode)
    rebuild = True
    if ledger_path.is_file():
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        if payload.get("mode") == mode and payload.get("user_count") == expected:
            rebuild = False
    if rebuild:
        run_stage2(mode=mode)
    return ledger_path


def _output_request_ids() -> list[str]:
    """Eval submission order from dataset/requests.csv."""
    with (DATASET_DIR / "requests.csv").open(newline="", encoding="utf-8") as handle:
        return [row["request_id"] for row in csv.DictReader(handle)]


def _write_output_csv(rows: list[dict[str, str]], path: Path) -> None:
    """Write final submission CSV with OUTPUT_COLUMNS header."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_stage3(
    mode: Mode = "all",
    regress_sample: bool = True,
    output_path: Path | None = None,
    use_llm_explanations: bool = True,
    offline_sample_explanations: bool = False,
) -> Stage3Result:
    """Stage 3 entry: decide per user, explain, write output.csv, optional regression."""
    reset_usage()
    reset_explanations_cache()
    ledger_path = _ensure_ledgers(mode)
    ledgers_by_user = _load_ledgers(ledger_path)

    contexts = load_user_context_rows()
    if mode == "sample":
        contexts = [c for c in contexts if c.data_source == "sample"]
    elif mode == "eval":
        contexts = [c for c in contexts if c.data_source == "eval"]
    # mode "all": process every context; submission output still uses eval request_ids only.

    decisions_by_request: dict[str, dict[str, str]] = {}
    sample_predictions: list[dict[str, str]] = []
    sample_labels: dict[str, dict[str, str]] = {}

    for context in contexts:
        ledger = ledgers_by_user.get(context.user_id)
        if not ledger:
            raise KeyError(f"Missing ledger for {context.user_id}")
        decision = decide_for_request(context, ledger)
        explanation = generate_decision_explanation(
            decision,
            context,
            ledger,
            use_llm=use_llm_explanations,
            offline_sample_explanations=offline_sample_explanations,
        )
        row = decision.to_output_dict(explanation)
        decisions_by_request[context.request_id] = row
        if context.data_source == "sample" and context.sample_labels:
            sample_predictions.append(row)
            sample_labels[context.request_id] = context.sample_labels

    regression_msg: str | None = None
    if regress_sample and sample_predictions:
        summary = run_sample_regression(sample_predictions, sample_labels)
        regression_msg = (
            f"Sample regression: {summary.passed}/{summary.total} passed "
            f"-> {summary.report_path}"
        )

    if mode == "sample":
        out_rows = [decisions_by_request[c.request_id] for c in contexts]
    else:
        eval_ids = _output_request_ids()
        missing = [rid for rid in eval_ids if rid not in decisions_by_request]
        if missing:
            raise KeyError(f"Missing decisions for eval requests: {missing[:5]}")
        out_rows = [decisions_by_request[rid] for rid in eval_ids]

    out = output_path or (REPO_ROOT / "output.csv")
    _write_output_csv(out_rows, out)

    if use_llm_explanations and not offline_sample_explanations:
        usage_path = get_usage().write_json()
        print(f"  LLM usage -> {usage_path}")

    return Stage3Result(
        output_path=out,
        row_count=len(out_rows),
        regression=regression_msg,
    )
