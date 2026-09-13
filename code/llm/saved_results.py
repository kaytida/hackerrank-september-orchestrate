"""Load precomputed explanations and image lookups from temp_data / output.csv."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from config import REPO_ROOT, TEMP_DATA_DIR

SAVED_EXPLANATIONS_FILENAME = "saved_decision_explanations.json"

_explanations_cache: dict[str, str] | None = None


def _load_explanations_from_json() -> dict[str, str]:
    path = TEMP_DATA_DIR / SAVED_EXPLANATIONS_FILENAME
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v).strip()
        for k, v in data.items()
        if v is not None and str(v).strip()
    }


def _load_explanations_from_output_csv() -> dict[str, str]:
    path = REPO_ROOT / "output.csv"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rid = (row.get("request_id") or "").strip()
            text = (row.get("decision_explanation") or "").strip()
            if rid and text:
                out[rid] = text
    return out


def load_saved_explanations() -> dict[str, str]:
    """Merge saved_decision_explanations.json with repo-root output.csv (csv wins on clash)."""
    global _explanations_cache
    if _explanations_cache is not None:
        return _explanations_cache
    merged = _load_explanations_from_json()
    merged.update(_load_explanations_from_output_csv())
    _explanations_cache = merged
    return merged


def get_saved_explanation(request_id: str) -> str | None:
    """Return a precomputed decision_explanation for request_id, if any."""
    text = load_saved_explanations().get(request_id)
    return text or None


def reset_explanations_cache() -> None:
    """Clear in-memory cache (e.g. before a new Stage 3 run)."""
    global _explanations_cache
    _explanations_cache = None
