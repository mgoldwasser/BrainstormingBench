"""Baseline adapter: one Claude Opus call, one simple brainstorming prompt.

This is intentionally uninteresting. It exists as a floor on the leaderboard
and as the corpus against which `metrics.originality` computes
"corpus-relative novelty": an idea is novel to the extent that a plain single
call to the frontier model would *not* have produced it.
"""

from __future__ import annotations

import os
import time
from typing import Any

from adapters.base import Adapter, Response, parse_ideas

# Model strings are pinned exactly — no date suffix.
_MODEL = "claude-opus-4-6"
_SYSTEM_PROMPT = (
    "You are a brainstorming partner. Given a problem, produce a numbered list "
    "of distinct ideas. One idea per line. No preamble, no conclusion."
)
_USER_TEMPLATE = (
    "Problem:\n{problem}\n\n"
    "Brainstorm at least 10 distinct ideas. Favor variety over polish."
)


class PlainClaudeAdapter(Adapter):
    """Single-call baseline using the Anthropic SDK.

    Configuration is deliberately minimal: default (high) reasoning effort,
    adaptive thinking, streaming (required for large max_tokens).
    """

    name = "plain_claude@0.1"

    def __init__(self, model: str = _MODEL, max_tokens: int = 8192) -> None:
        self._model = model
        self._max_tokens = max_tokens

    def generate(self, problem: str) -> Response:
        from anthropic import Anthropic  # imported lazily; tests patch this

        client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

        started = time.time()
        # Stream any call with max_tokens > 4096.
        raw_chunks: list[str] = []
        usage: dict[str, Any] = {}
        with client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": _USER_TEMPLATE.format(problem=problem)}],
        ) as stream:
            for text in stream.text_stream:
                raw_chunks.append(text)
            final = stream.get_final_message()
            if final.usage is not None:
                usage = {
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                }

        raw = "".join(raw_chunks)
        latency = time.time() - started

        ideas = parse_ideas(raw, origin="plain_claude")
        return Response(
            problem_id="",  # filled in by the run harness
            system=self.name,
            ideas=ideas,
            raw=raw,
            meta={
                "model": self._model,
                "latency_s": round(latency, 2),
                **usage,
            },
        )
