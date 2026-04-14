"""Elaboration: how fleshed-out each idea is.

Reports two numbers:

- `mean_tokens_per_idea` — a whitespace-token proxy for idea length.
- `mechanism_coverage` — the fraction of ideas whose text contains at least
  one mechanism word ("because", "by", "via", "so that") OR at least one
  example marker ("e.g.", "for example", "such as", "like"). We collapse
  both into a single "is there *any* justification or illustration?" signal,
  which is what the elaboration construct actually cares about.
"""

from __future__ import annotations

import re

from metrics._types import Response

# Mechanism words — any of these suggest the idea carries an explanation of
# *why* or *how* it works, not just what it is.
_MECHANISM_RE = re.compile(
    r"""
        \b(?:
            because
          | since
          | thereby
          | through
          | due\s+to
          | so\s+that
          | so\s+as\s+to
          | in\s+order\s+to
          | leads?\s+to
          | causes?
          | via
          | by\s+\w       # "by doing X" — intentionally no trailing \b
        )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Example markers — the idea is illustrated with a concrete case.
_EXAMPLE_RE = re.compile(
    r"""
        (?:
            \be\.g\.
          | \bi\.e\.
          | \bfor\s+example\b
          | \bfor\s+instance\b
          | \bsuch\s+as\b
          | \blike\s+\w   # "like a coffee subscription"
          | \bfor\s+one\b
        )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _tokens(text: str) -> int:
    return len(re.findall(r"\S+", text))


def elaboration(response: Response) -> dict[str, float]:
    ideas = [i for i in response.ideas if i.text.strip()]
    if not ideas:
        return {
            "mean_tokens_per_idea": 0.0,
            "mechanism_coverage": 0.0,
            "example_coverage": 0.0,
            "any_justification_coverage": 0.0,
        }

    token_counts = [_tokens(i.text) for i in ideas]
    mechanism_hits = sum(1 for i in ideas if _MECHANISM_RE.search(i.text))
    example_hits = sum(1 for i in ideas if _EXAMPLE_RE.search(i.text))
    any_hits = sum(
        1 for i in ideas
        if _MECHANISM_RE.search(i.text) or _EXAMPLE_RE.search(i.text)
    )
    n = len(ideas)
    return {
        "mean_tokens_per_idea": sum(token_counts) / n,
        "mechanism_coverage": mechanism_hits / n,
        "example_coverage": example_hits / n,
        "any_justification_coverage": any_hits / n,
    }


__all__ = ["elaboration"]
