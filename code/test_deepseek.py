"""
Smoke test for DeepSeek platform API.

Run from repository root:
  python code/test_deepseek.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_CODE_DIR = Path(__file__).resolve().parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from config import REPO_ROOT
from llm.deepseek import (
    DEFAULT_MODEL,
    DEEPSEEK_CHAT_URL,
    assistant_message_from_response,
    chat_completions,
)
from llm.secrets import load_deepseek_api_key


def main() -> int:
    """Smoke-test DeepSeek with two chat turns and print token usage."""
    api_key = load_deepseek_api_key()
    print(f"Endpoint: {DEEPSEEK_CHAT_URL}")
    print(f"Model: {DEFAULT_MODEL}")
    print(f"Secrets file: {REPO_ROOT / '.secrets.json'}")

    first_user = "How many r's are in the word 'strawberry'?"
    response1 = chat_completions(
        api_key,
        [{"role": "user", "content": first_user}],
    )
    assistant1 = assistant_message_from_response(response1)
    content1 = assistant1.get("content") or ""
    print("\n--- Turn 1 (assistant) ---")
    print(content1[:800] + ("..." if len(content1) > 800 else ""))

    messages = [
        {"role": "user", "content": first_user},
        {"role": "assistant", "content": assistant1.get("content")},
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

    print("\nOK: DeepSeek chat completions succeeded (2 turns).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        print(f"\nFAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
