"""OpenRouter chat completions client."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "inclusionai/ling-3.0-flash-fin:free"


def chat_completions(
    api_key: str,
    messages: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    reasoning_enabled: bool = True,
    timeout: float = 120.0,
    referer: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """POST /chat/completions; returns the parsed JSON body."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if reasoning_enabled:
        body["reasoning"] = {"enabled": True}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title

    req = Request(
        OPENROUTER_CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenRouter HTTP {exc.code}: {detail[:500]}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc.reason}") from exc


def assistant_message_from_response(response: dict[str, Any]) -> dict[str, Any]:
    """Return the first choice message dict."""
    choices = response.get("choices")
    if not choices:
        raise RuntimeError(f"OpenRouter response missing choices: {response}")
    return choices[0]["message"]
