from __future__ import annotations

import csv
import json
from pathlib import Path

from config import TEMP_DATA_DIR, USER_CONTEXT_FILENAME
from stage2.models import UserContextRow


def _split_pipe(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    return [part.strip() for part in value.split("|") if part.strip()]


def _parse_bool(value: str) -> bool:
    return (value or "").strip().lower() in ("true", "1", "yes")


def _parse_optional_int(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    return int(value)


def _parse_sample_labels(raw: str) -> dict[str, str] | None:
    if not raw or raw.strip() in ("", "null"):
        return None
    data = json.loads(raw)
    return data if isinstance(data, dict) else None


def row_from_csv_dict(row: dict[str, str]) -> UserContextRow:
    sample_labels = _parse_sample_labels(row.get("sample_labels_json", ""))
    return UserContextRow(
        user_id=row["user_id"],
        request_id=row["request_id"],
        data_source=row["data_source"],
        home_currency=row["home_currency"],
        current_available_balance=float(row["current_available_balance"]),
        minimum_balance_to_keep=float(row["minimum_balance_to_keep"]),
        financial_priorities=_split_pipe(row["financial_priorities"]),
        expense_categories_to_protect=_split_pipe(row["expense_categories_to_protect"]),
        expense_categories_user_is_willing_to_reduce=_split_pipe(
            row["expense_categories_user_is_willing_to_reduce"]
        ),
        expense_categories_user_is_willing_to_stop=_split_pipe(
            row["expense_categories_user_is_willing_to_stop"]
        ),
        payment_methods_user_will_consider=_split_pipe(
            row["payment_methods_user_will_consider"]
        ),
        max_installment_months=_parse_optional_int(row["max_installment_months"]),
        request_date=row["request_date"],
        request_type=row["request_type"],
        requested_amount=float(row["requested_amount"]),
        desired_completion_date=row["desired_completion_date"],
        allows_partial_payment=_parse_bool(row["allows_partial_payment"]),
        request_text=row["request_text"],
        payment_options=json.loads(row["payment_options_json"]),
        financial_events=json.loads(row["financial_events_json"]),
        messages=json.loads(row["messages_json"]),
        images=json.loads(row["images_json"]),
        sample_labels=sample_labels,
    )


def load_user_context_rows(
    path: Path | None = None,
    data_source: str | None = None,
) -> list[UserContextRow]:
    csv_path = path or (TEMP_DATA_DIR / USER_CONTEXT_FILENAME)
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"user_context not found at {csv_path}. Run Stage 1 first "
            f"(python code/main.py --stage1-only)."
        )
    rows: list[UserContextRow] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            if data_source and raw.get("data_source") != data_source:
                continue
            rows.append(row_from_csv_dict(raw))
    return rows
