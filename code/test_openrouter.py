"""
Smoke test for OpenRouter (reasoning + multi-turn with reasoning_details).

Run from repository root:
  python code/test_openrouter.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_CODE_DIR = Path(__file__).resolve().parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from config import REPO_ROOT
from llm.openrouter import (
    DEFAULT_MODEL,
    assistant_message_from_response,
    chat_completions,
)
from llm.secrets import load_openrouter_api_key


def main() -> int:
    api_key = load_openrouter_api_key()
    print(f"Using model: {DEFAULT_MODEL}")
    print(f"Secrets file: {REPO_ROOT / '.secrets.json'}")

    first_user = "How many r's are in the word 'strawberry'?"
    response1 = chat_completions(
        api_key,
        [{"role": "user", "content": first_user}],
        referer="https://github.com/hackerrank-orchestrate",
        title="Buy or Wait OpenRouter test",
    )
    assistant1 = assistant_message_from_response(response1)
    content1 = assistant1.get("content") or ""
    print("\n--- Turn 1 (assistant) ---")
    print(content1[:800] + ("..." if len(content1) > 800 else ""))
    if assistant1.get("reasoning_details") is not None:
        print("(reasoning_details present on assistant message)")

    messages = [
        {"role": "user", "content": first_user},
        {
            "role": "assistant",
            "content": assistant1.get("content"),
            "reasoning_details": assistant1.get("reasoning_details"),
        },
        {"role": "user", "content": "Are you sure? Think carefully."},
    ]
    response2 = chat_completions(api_key, messages)
    assistant2 = assistant_message_from_response(response2)
    content2 = assistant2.get("content") or ""
    print("\n--- Turn 2 (assistant) ---")
    print(content2[:800] + ("..." if len(content2) > 800 else ""))

    usage = response2.get("usage") or response1.get("usage")
    if usage:
        print(f"\nToken usage (last response): {usage}")

    if not content1.strip() or not content2.strip():
        print("\nFAIL: empty assistant content in one or both turns.")
        return 1

    print("\nOK: OpenRouter chat completions succeeded (2 turns).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        print(f"\nFAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
