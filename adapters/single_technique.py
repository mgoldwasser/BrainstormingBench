"""Baseline adapter: one Claude call wrapped in a single named technique.

Useful as a second, stronger floor: it asks the model to brainstorm *in the
style of a particular technique* rather than a plain list. The default
technique is "stoner circle" — a playful, lateral reframing — but any
technique string can be passed.

This exists mostly to check that "any technique" beats "no technique". If it
doesn't, that's a signal the harness or metrics are broken.

Transport follows `adapters._transport.default_transport()` — CLI (subscription)
by default, SDK (API key) via `BENCH_TRANSPORT=api`.
"""

from __future__ import annotations

from adapters._transport import (
    DEFAULT_GENERATOR_MODEL,
    default_transport,
    generate_via_api,
    generate_via_cli,
)
from adapters.base import Adapter, Response, parse_ideas

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
        model: str = DEFAULT_GENERATOR_MODEL,
        max_tokens: int = 8192,
        transport: str | None = None,
    ) -> None:
        if technique not in _TECHNIQUES:
            raise ValueError(
                f"unknown technique {technique!r}; known: {sorted(_TECHNIQUES)}"
            )
        self._technique = technique
        self._model = model
        self._max_tokens = max_tokens
        self._transport = transport or default_transport()
        self.name = f"single_technique[{technique}]@0.2"

    def generate(self, problem: str) -> Response:
        system = _SYSTEM_TEMPLATE.format(technique_body=_TECHNIQUES[self._technique])
        user = f"Problem:\n{problem}"

        if self._transport == "cli":
            raw, meta = generate_via_cli(
                system_prompt=system,
                user_prompt=user,
                model=self._model,
            )
        else:
            raw, meta = generate_via_api(
                system_prompt=system,
                user_prompt=user,
                model=self._model,
                max_tokens=self._max_tokens,
            )

        meta["technique"] = self._technique
        return Response(
            problem_id="",
            system=self.name,
            ideas=parse_ideas(raw, origin=self._technique),
            raw=raw,
            meta=meta,
        )
