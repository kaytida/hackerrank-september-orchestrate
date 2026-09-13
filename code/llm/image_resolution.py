"""Resolve blank event amounts from receipt images via DeepSeek (vision when supported)."""

from __future__ import annotations

import base64
import csv
import json
import re
from pathlib import Path
from typing import Any

from config import DATASET_DIR
from llm.deepseek import DEFAULT_MODEL, assistant_message_from_response, chat_completions
from llm.secrets import load_deepseek_api_key

_events_by_id: dict[str, dict[str, str]] | None = None


def _load_events() -> dict[str, dict[str, str]]:
    global _events_by_id
    if _events_by_id is not None:
        return _events_by_id
    path = DATASET_DIR / "financial_events.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        _events_by_id = {row["event_id"]: row for row in csv.DictReader(handle)}
    return _events_by_id


def _parse_amount(text: str) -> str | None:
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    return match.group(0)


def _resolve_one_image(
    api_key: str,
    image_id: str,
    related_event_id: str,
    request_id: str,
) -> dict[str, str] | None:
    """Return quick_lookup entry for one image, or None if the LLM call fails."""
    events = _load_events()
    event = events.get(related_event_id)
    if not event:
        return None

    png = DATASET_DIR / "media" / "images" / f"{image_id}.png"
    currency = event.get("currency", "")
    description = event.get("description", "")
    system = (
        "You read financial document images. Reply with ONLY a JSON object: "
        '{"resolved_amount":"<number>","resolved_amount_rationale":"<short reason>"}. '
        "Use the document's amount in the stated currency; no markdown."
    )
    user_text = (
        f"request_id={request_id}, event_id={related_event_id}, "
        f"description={description}, currency={currency}. "
        "Extract the cash amount that should fill the blank amount on this event."
    )

    messages: list[dict[str, Any]]
    if png.is_file():
        b64 = base64.standard_b64encode(png.read_bytes()).decode("ascii")
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            },
        ]
    else:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]

    response = chat_completions(api_key, messages, model=DEFAULT_MODEL, timeout=180.0)
    message = assistant_message_from_response(response)
    content = (message.get("content") or "").strip()
    if not content:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        amount = _parse_amount(content)
        if not amount:
            return None
        payload = {"resolved_amount": amount, "resolved_amount_rationale": content[:200]}
    amount = str(payload.get("resolved_amount", "")).strip()
    if not amount:
        amount = _parse_amount(content) or ""
    if not amount:
        return None
    return {
        "resolved_amount": amount,
        "resolved_amount_rationale": str(
            payload.get("resolved_amount_rationale") or "DeepSeek image extraction"
        ),
        "image_id": image_id,
        "request_id": request_id,
    }


def build_image_lookup_via_llm(
    saved_lookup: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """
    Try DeepSeek per dataset image; use saved_lookup entries when a call fails.
    """
    api_key = load_deepseek_api_key()
    images_path = DATASET_DIR / "images.csv"
    lookup: dict[str, dict[str, str]] = {}

    with images_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    for row in rows:
        event_id = row["related_event_id"]
        image_id = row["image_id"]
        request_id = row["request_id"]
        try:
            entry = _resolve_one_image(api_key, image_id, event_id, request_id)
            if entry:
                lookup[event_id] = entry
                continue
        except Exception:
            pass
        if event_id in saved_lookup:
            lookup[event_id] = saved_lookup[event_id]

    return lookup
