from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import IMAGES_LOOKUP_FILENAME, TEMP_DATA_DIR


def _load_images_document(path: Path | None = None) -> dict[str, Any]:
    """Read temp_data/images.json if present; otherwise return {}."""
    json_path = path or (TEMP_DATA_DIR / IMAGES_LOOKUP_FILENAME)
    if not json_path.is_file():
        return {}
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_image_amount_lookup(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Return event_id -> resolved amount metadata from images.json quick_lookup."""
    data = _load_images_document(path)
    quick = data.get("quick_lookup", {})
    if not isinstance(quick, dict):
        return {}
    return quick


def image_evidence_for_request(
    request_id: str,
    path: Path | None = None,
) -> list[dict[str, str]]:
    """Summaries from temp_data/images.json for LLM context (no vision calls)."""
    data = _load_images_document(path)
    images = data.get("images", [])
    if not isinstance(images, list):
        return []
    evidence: list[dict[str, str]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        if image.get("request_id") != request_id:
            continue
        evidence.append(
            {
                "image_id": str(image.get("image_id", "")),
                "document_type": str(image.get("document_type", "")),
                "summary": str(image.get("summary", "")),
                "related_event_id": str(image.get("related_event_id", "")),
                "resolved_amount": str(image.get("resolved_amount", "")),
                "resolved_amount_rationale": str(
                    image.get("resolved_amount_rationale", "")
                ),
            }
        )
    return evidence


def apply_image_amounts(
    events: list[dict[str, str]],
    lookup: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Fill blank event amounts from the image lookup and tag _amount_source."""
    patched: list[dict[str, str]] = []
    for event in events:
        event_id = event["event_id"]
        amount = (event.get("amount") or "").strip()
        if amount:
            patched.append(dict(event))
            continue
        entry = lookup.get(event_id)
        if not entry:
            patched.append(dict(event))
            continue
        resolved = entry.get("resolved_amount", "").strip()
        if not resolved:
            patched.append(dict(event))
            continue
        updated = dict(event)
        updated["amount"] = resolved
        updated["_amount_source"] = "images_json"
        patched.append(updated)
    return patched
