"""Baseline adapter: one Claude Opus call, one simple brainstorming prompt.

Transport is chosen by `default_transport()`:
    - `cli` (default if `claude` is on PATH): routes through `claude -p`,
      uses the Claude Code subscription, no API key needed.
    - `api`: uses the Anthropic SDK directly; needs ANTHROPIC_API_KEY.
      Opt-in via `BENCH_TRANSPORT=api`.

This is intentionally uninteresting. It exists as a floor on the leaderboard
and as the corpus against which `metrics.originality` computes
"corpus-relative novelty": an idea is novel to the extent that a plain single
call to the frontier model would *not* have produced it.
"""

from __future__ import annotations

from adapters._transport import (
    DEFAULT_GENERATOR_MODEL,
    default_transport,
    generate_via_api,
    generate_via_cli,
)
from adapters.base import Adapter, Response, parse_ideas

_SYSTEM_PROMPT = (
    "You are a brainstorming partner. Given a problem, produce a numbered list "
    "of distinct ideas. One idea per line. No preamble, no conclusion."
)
_USER_TEMPLATE = (
    "Problem:\n{problem}\n\n"
    "Brainstorm at least 10 distinct ideas. Favor variety over polish."
)


class PlainClaudeAdapter(Adapter):
    """Single-call baseline."""

    name = "plain_claude@0.2"

    def __init__(
        self,
        model: str = DEFAULT_GENERATOR_MODEL,
        max_tokens: int = 8192,
        transport: str | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._transport = transport or default_transport()

    def generate(self, problem: str) -> Response:
        user_prompt = _USER_TEMPLATE.format(problem=problem)
        if self._transport == "cli":
            raw, meta = generate_via_cli(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=self._model,
            )
        else:
            raw, meta = generate_via_api(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=self._model,
                max_tokens=self._max_tokens,
            )

        return Response(
            problem_id="",  # filled in by the run harness
            system=self.name,
            ideas=parse_ideas(raw, origin="plain_claude"),
            raw=raw,
            meta=meta,
        )
