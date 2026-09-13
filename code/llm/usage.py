"""Aggregate DeepSeek token usage across a pipeline run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import TEMP_DATA_DIR

LLM_USAGE_FILENAME = "llm_usage.json"


@dataclass
class LlmUsageAccumulator:
    provider: str = "deepseek"
    model: str = ""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    failures: int = 0

    def record_success(self, response: dict[str, Any], model: str) -> None:
        """Accumulate token usage from a successful chat completion response."""
        self.model = model
        self.calls += 1
        usage = response.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or prompt + completion)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total

    def record_failure(self) -> None:
        """Increment failure count when an LLM call errors."""
        self.failures += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize usage stats for llm_usage.json."""
        avg = self.total_tokens / self.calls if self.calls else 0.0
        return {
            "provider": self.provider,
            "model": self.model,
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "average_total_tokens_per_call": round(avg, 2),
            "failures": self.failures,
        }

    def write_json(self, path: Path | None = None) -> Path:
        """Write accumulated usage to temp_data/llm_usage.json."""
        out = path or (TEMP_DATA_DIR / LLM_USAGE_FILENAME)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return out


_session: LlmUsageAccumulator | None = None


def reset_usage() -> LlmUsageAccumulator:
    """Clear session usage at the start of a pipeline run."""
    global _session
    _session = LlmUsageAccumulator()
    return _session


def get_usage() -> LlmUsageAccumulator:
    """Return the current run's LLM usage accumulator (lazy-init)."""
    global _session
    if _session is None:
        _session = LlmUsageAccumulator()
    return _session
