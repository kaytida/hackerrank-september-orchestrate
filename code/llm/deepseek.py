"""DeepSeek chat completions client (platform API only)."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


def chat_completions(
    api_key: str,
    messages: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    reasoning_enabled: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """POST /chat/completions; returns the parsed JSON body."""
    body: dict[str, Any] = {"model": model, "messages": messages}
    if reasoning_enabled and model != "deepseek-reasoner":
        body["model"] = "deepseek-reasoner"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "BuyOrWait/1.0 (Python)",
    }
    req = Request(
        DEEPSEEK_CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"DeepSeek request failed: {exc.reason}") from exc


def assistant_message_from_response(response: dict[str, Any]) -> dict[str, Any]:
    """Return the first choice message dict."""
    choices = response.get("choices")
    if not choices:
        raise RuntimeError(f"DeepSeek response missing choices: {response}")
    return choices[0]["message"]
