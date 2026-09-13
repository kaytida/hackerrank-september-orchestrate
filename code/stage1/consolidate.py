"""Stage 1: build one-row-per-user user_context.csv from raw dataset files."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from config import (
    DATASET_DIR,
    PROFILE_COLUMNS,
    REQUEST_INPUT_COLUMNS,
    SAMPLE_LABEL_COLUMNS,
    TEMP_DATA_DIR,
    USER_CONTEXT_FILENAME,
)

Mode = Literal["all", "sample", "eval"]

USER_CONTEXT_SCALAR_COLUMNS = [
    "user_id",
    "request_id",
    "data_source",
    *PROFILE_COLUMNS,
    *REQUEST_INPUT_COLUMNS[2:],  # request fields except user_id (duplicate key)
]

USER_CONTEXT_JSON_COLUMNS = [
    "payment_options_json",
    "financial_events_json",
    "messages_json",
    "images_json",
    "sample_labels_json",
]

OUTPUT_COLUMNS = USER_CONTEXT_SCALAR_COLUMNS + USER_CONTEXT_JSON_COLUMNS


@dataclass(frozen=True)
class ConsolidationResult:
    """Paths and counts produced by Stage 1 consolidation."""

    output_path: Path
    row_count: int
    mode: Mode


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Load a UTF-8 CSV file into a list of row dictionaries."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _json_dumps(value: Any) -> str:
    """Serialize nested structures for CSV JSON columns (compact, no ASCII escape)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _image_path(image_id: str) -> str:
    """Return the dataset-relative path string stored in user_context for an image."""
    return f"dataset/media/images/{image_id}.png"


def _enrich_images(images: list[dict[str, str]]) -> list[dict[str, str]]:
    """Attach image_path and image_file_present to each image metadata row."""
    enriched: list[dict[str, str]] = []
    for row in images:
        image_id = row["image_id"]
        path = DATASET_DIR / "media" / "images" / f"{image_id}.png"
        enriched.append(
            {
                **row,
                "image_path": _image_path(image_id),
                "image_file_present": str(path.is_file()),
            }
        )
    return enriched


def _sample_labels_from_row(row: dict[str, str]) -> dict[str, str]:
    """Extract gold label columns from a sample_requests.csv row."""
    return {key: row.get(key, "") for key in SAMPLE_LABEL_COLUMNS}


def _validate_referential_integrity(
    users: list[str],
    profiles: dict[str, dict[str, str]],
    events_by_user: dict[str, list[dict[str, str]]],
    payment_options_by_request: dict[str, list[dict[str, str]]],
    requests_by_user: dict[str, dict[str, str]],
    images_by_user: dict[str, list[dict[str, str]]],
) -> None:
    """Raise ValueError if dataset links, counts, or image files are inconsistent."""
    errors: list[str] = []
    for user_id in users:
        if user_id not in profiles:
            errors.append(f"missing profile for {user_id}")
        if user_id not in requests_by_user:
            errors.append(f"missing request for {user_id}")
        if user_id not in events_by_user or not events_by_user[user_id]:
            errors.append(f"missing events for {user_id}")

        request = requests_by_user.get(user_id)
        if not request:
            continue
        request_id = request["request_id"]
        options = payment_options_by_request.get(request_id, [])
        if not (2 <= len(options) <= 4):
            errors.append(
                f"{request_id}: expected 2-4 payment options, got {len(options)}"
            )

        event_ids = {e["event_id"] for e in events_by_user.get(user_id, [])}
        for image in images_by_user.get(user_id, []):
            related = image.get("related_event_id", "")
            if related and related not in event_ids:
                errors.append(
                    f"{user_id}: image {image['image_id']} references unknown event {related}"
                )
            if image.get("image_file_present") != "True":
                errors.append(
                    f"{user_id}: missing image file for {image.get('image_id')}"
                )

        for event in events_by_user.get(user_id, []):
            amount = (event.get("amount") or "").strip()
            if amount:
                continue
            event_id = event["event_id"]
            linked = [
                img
                for img in images_by_user.get(user_id, [])
                if img.get("related_event_id") == event_id
            ]
            if not linked:
                errors.append(f"{user_id}: blank amount on {event_id} without image link")

    if errors:
        raise ValueError("Stage 1 validation failed:\n" + "\n".join(errors))


def _build_request_maps() -> tuple[
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
    dict[str, Literal["sample", "eval"]],
]:
    """Map user_id -> request row and data_source. Sample and eval are disjoint."""
    eval_rows = _read_csv(DATASET_DIR / "requests.csv")
    sample_rows = _read_csv(DATASET_DIR / "sample_requests.csv")

    by_user: dict[str, dict[str, str]] = {}
    source: dict[str, Literal["sample", "eval"]] = {}

    for row in eval_rows:
        user_id = row["user_id"]
        if user_id in by_user:
            raise ValueError(f"duplicate eval user_id {user_id}")
        by_user[user_id] = row
        source[user_id] = "eval"

    for row in sample_rows:
        user_id = row["user_id"]
        if user_id in by_user:
            raise ValueError(f"duplicate sample user_id {user_id}")
        by_user[user_id] = row
        source[user_id] = "sample"

    sample_by_user = {row["user_id"]: row for row in sample_rows}
    return by_user, sample_by_user, source


def _select_users(
    source: dict[str, Literal["sample", "eval"]], mode: Mode
) -> list[str]:
    """Return sorted user_ids included for the given pipeline mode."""
    if mode == "all":
        return sorted(source.keys(), key=_user_sort_key)
    if mode == "sample":
        return sorted(
            [u for u, s in source.items() if s == "sample"], key=_user_sort_key
        )
    if mode == "eval":
        return sorted(
            [u for u, s in source.items() if s == "eval"], key=_user_sort_key
        )
    raise ValueError(f"unknown mode: {mode}")


def _user_sort_key(user_id: str) -> int:
    """Sort key: numeric suffix of user_NNN, else 0."""
    if user_id.startswith("user_"):
        return int(user_id.split("_", 1)[1])
    return 0


def build_user_context_rows(mode: Mode = "all") -> list[dict[str, str]]:
    """Join dataset tables into one dict per user, validated and filtered by mode."""
    profiles_list = _read_csv(DATASET_DIR / "financial_profiles.csv")
    profiles = {row["user_id"]: row for row in profiles_list}

    events_by_user: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(DATASET_DIR / "financial_events.csv"):
        events_by_user[row["user_id"]].append(row)

    messages_by_user: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(DATASET_DIR / "messages.csv"):
        messages_by_user[row["user_id"]].append(row)

    images_by_user: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(DATASET_DIR / "images.csv"):
        images_by_user[row["user_id"]].append(row)

    payment_options_by_request: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(DATASET_DIR / "request_payment_options.csv"):
        payment_options_by_request[row["request_id"]].append(row)
    for request_id, options in payment_options_by_request.items():
        options.sort(key=lambda r: r["payment_option_id"])

    requests_by_user, sample_by_user, source = _build_request_maps()
    users = _select_users(source, mode)

    enriched_images_by_user = {
        user_id: _enrich_images(images_by_user.get(user_id, []))
        for user_id in users
    }

    _validate_referential_integrity(
        users,
        profiles,
        events_by_user,
        payment_options_by_request,
        requests_by_user,
        enriched_images_by_user,
    )

    rows: list[dict[str, str]] = []
    for user_id in users:
        profile = profiles[user_id]
        request = requests_by_user[user_id]
        request_id = request["request_id"]
        data_source = source[user_id]

        payment_options = payment_options_by_request[request_id]
        events = events_by_user[user_id]
        messages = messages_by_user.get(user_id, [])
        images = enriched_images_by_user.get(user_id, [])

        sample_labels: dict[str, str] | None = None
        if data_source == "sample":
            sample_labels = _sample_labels_from_row(sample_by_user[user_id])

        row: dict[str, str] = {
            "user_id": user_id,
            "request_id": request_id,
            "data_source": data_source,
        }
        for col in PROFILE_COLUMNS:
            row[col] = profile[col]
        for col in REQUEST_INPUT_COLUMNS[2:]:
            row[col] = request[col]

        row["payment_options_json"] = _json_dumps(payment_options)
        row["financial_events_json"] = _json_dumps(events)
        row["messages_json"] = _json_dumps(messages)
        row["images_json"] = _json_dumps(images)
        row["sample_labels_json"] = _json_dumps(sample_labels)

        rows.append(row)

    return rows


def write_user_context_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    """Write consolidated rows to user_context.csv with the fixed OUTPUT_COLUMNS schema."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_stage1(mode: Mode = "all") -> ConsolidationResult:
    """Stage 1 entry: build user_context.csv under temp_data and return result metadata."""
    rows = build_user_context_rows(mode=mode)
    output_path = TEMP_DATA_DIR / USER_CONTEXT_FILENAME
    write_user_context_csv(rows, output_path)
    return ConsolidationResult(output_path=output_path, row_count=len(rows), mode=mode)
