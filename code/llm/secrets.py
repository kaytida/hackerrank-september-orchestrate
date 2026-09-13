"""Load API keys from repo-local .secrets.json (gitignored) or environment."""

from __future__ import annotations

import json
import os
from pathlib import Path

from config import REPO_ROOT

SECRETS_PATH = REPO_ROOT / ".secrets.json"

_OPENROUTER_KEY_NAMES = (
    "OPENROUTER_API_KEY",
    "openrouter_api_key",
    "openrouter",
)


def load_openrouter_api_key() -> str:
    env = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if env:
        return env

    if not SECRETS_PATH.is_file():
        raise FileNotFoundError(
            f"Missing {SECRETS_PATH}. Create it with OPENROUTER_API_KEY "
            "or set the OPENROUTER_API_KEY environment variable."
        )

    data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{SECRETS_PATH} must be a JSON object.")

    for name in _OPENROUTER_KEY_NAMES:
        value = data.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()

    raise KeyError(
        f"No OpenRouter key in {SECRETS_PATH}. "
        f"Expected one of: {', '.join(_OPENROUTER_KEY_NAMES)}"
    )
