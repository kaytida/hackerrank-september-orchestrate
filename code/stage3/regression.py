"""Compare pipeline output to sample gold labels for local accuracy measurement only.

Gold fields must not be used to tune decision logic (see config amount_safe policy).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import TEMP_DATA_DIR
from stage3.models import OUTPUT_COLUMNS

REGRESSION_REPORT_FILENAME = "regression_report.json"

COMPARE_FIELDS = [
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
]


@dataclass(frozen=True)
class RegressionSummary:
    total: int
    passed: int
    failed: int
    report_path: Path


def _parse_amount(value: str) -> float:
    return float(value) if value else 0.0


def _amounts_close(a: str, b: str, tol: float = 1.0) -> bool:
    return abs(_parse_amount(a) - _parse_amount(b)) <= tol


def compare_to_labels(
    predicted: dict[str, str],
    labels: dict[str, str],
    amount_tolerance: float = 0.0,
) -> dict[str, Any]:
    mismatches: list[dict[str, str]] = []
    for field in COMPARE_FIELDS:
        pred = (predicted.get(field) or "").strip()
        gold = (labels.get(field) or "").strip()
        if field == "amount_safe_to_pay":
            if not _amounts_close(pred, gold, amount_tolerance):
                mismatches.append({"field": field, "predicted": pred, "expected": gold})
        elif pred != gold:
            mismatches.append({"field": field, "predicted": pred, "expected": gold})
    return {
        "request_id": predicted["request_id"],
        "passed": len(mismatches) == 0,
        "mismatches": mismatches,
    }


def run_sample_regression(
    predictions: list[dict[str, str]],
    sample_labels_by_request: dict[str, dict[str, str]],
    amount_tolerance: float = 1.0,
) -> RegressionSummary:
    results: list[dict[str, Any]] = []
    passed = 0
    for row in predictions:
        request_id = row["request_id"]
        labels = sample_labels_by_request.get(request_id)
        if not labels:
            continue
        outcome = compare_to_labels(row, labels, amount_tolerance=amount_tolerance)
        results.append(outcome)
        if outcome["passed"]:
            passed += 1
    total = len(results)
    report = {
        "total_sample_requests": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "amount_tolerance": amount_tolerance,
        "results": results,
    }
    path = TEMP_DATA_DIR / REGRESSION_REPORT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return RegressionSummary(
        total=total, passed=passed, failed=total - passed, report_path=path
    )
