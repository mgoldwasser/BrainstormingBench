"""Baseline adapter: one Claude call wrapped in a single named technique.

Useful as a second, stronger floor: it asks the model to brainstorm *in the
style of a particular technique* rather than a plain list. The default
technique is "stoner circle" — a playful, lateral reframing — but any
technique string can be passed.

This exists mostly to check that "any technique" beats "no technique". If it
doesn't, that's a signal the harness or metrics are broken.
"""

from __future__ import annotations

import os
import time
from typing import Any

from adapters.base import Adapter, Response, parse_ideas

_MODEL = "claude-opus-4-6"

_TECHNIQUES: dict[str, str] = {
    "stoner_circle": (
        "Imagine a group of friends on a couch, riffing on the problem with "
        "zero self-censorship. Each idea should feel slightly absurd at first "
        "glance but contain a real kernel. Lean into free association: "
        "'what if...', 'wait, actually...', 'ok but what about...'."
    ),
    "first_principles": (
        "Break the problem down to its physical / economic / social "
        "fundamentals. For each fundamental, propose an idea that operates "
        "directly on that layer rather than on its visible surface."
    ),
    "worst_idea": (
        "Deliberately brainstorm the *worst* possible ideas first, then "
        "invert each one into a useful proposal. The final list contains "
        "only the inverted ideas, but they should carry the energy of their "
        "terrible origins."
    ),
}

_SYSTEM_TEMPLATE = (
    "You are a brainstorming partner using a specific technique:\n\n"
    "{technique_body}\n\n"
    "Output a numbered list of at least 10 distinct ideas. One per line. No "
    "preamble, no conclusion."
)


class SingleTechniqueAdapter(Adapter):
    """Single-call, single-technique baseline."""

    def __init__(
        self,
        technique: str = "stoner_circle",
        model: str = _MODEL,
        max_tokens: int = 8192,
    ) -> None:
        if technique not in _TECHNIQUES:
            raise ValueError(
                f"unknown technique {technique!r}; known: {sorted(_TECHNIQUES)}"
            )
        self._technique = technique
        self._model = model
        self._max_tokens = max_tokens
        self.name = f"single_technique[{technique}]@0.1"

    def generate(self, problem: str) -> Response:
        from anthropic import Anthropic

        client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

        system = _SYSTEM_TEMPLATE.format(technique_body=_TECHNIQUES[self._technique])
        started = time.time()
        raw_chunks: list[str] = []
        usage: dict[str, Any] = {}
        with client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": f"Problem:\n{problem}"}],
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
        ideas = parse_ideas(raw, origin=self._technique)
        return Response(
            problem_id="",
            system=self.name,
            ideas=ideas,
            raw=raw,
            meta={
                "model": self._model,
                "technique": self._technique,
                "latency_s": round(latency, 2),
                **usage,
            },
        )
