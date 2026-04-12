"""Adapter ABC and shared data types.

An Adapter is any thing that, given a problem prompt, returns a `Response`
containing a list of `Idea` objects parsed from a verbatim `raw` output. The
benchmark never reaches inside a brainstorming system: it only sees what the
adapter chooses to emit.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# data types
# ---------------------------------------------------------------------------

@dataclass
class Idea:
    text: str                       # the idea itself, one sentence or short paragraph
    origin: str | None = None       # optional: which technique / agent produced it

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Response:
    problem_id: str
    system: str                     # adapter.name — includes version, e.g. "plain_claude@0.1"
    ideas: list[Idea]
    raw: str                        # full verbatim output of the brainstorming system
    meta: dict[str, Any] = field(default_factory=dict)

    # --- persistence ------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "system": self.system,
            "ideas": [i.to_json() for i in self.ideas],
            "raw": self.raw,
            "meta": self.meta,
        }

    def save(self, out_dir: str | Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # id is (problem_id).json — one problem per file per run directory
        path = out_dir / f"{self.problem_id}.json"
        path.write_text(json.dumps(self.to_json(), indent=2, ensure_ascii=False))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Response":
        data = json.loads(Path(path).read_text())
        return cls(
            problem_id=data["problem_id"],
            system=data["system"],
            ideas=[Idea(**i) for i in data["ideas"]],
            raw=data["raw"],
            meta=data.get("meta", {}),
        )


# ---------------------------------------------------------------------------
# abstract adapter
# ---------------------------------------------------------------------------

class Adapter(ABC):
    """Override `name` and `generate`. Nothing else is required."""

    # Immutable identifier including a version tag. Examples:
    #   "plain_claude@0.1"
    #   "brainstorm-kit@1.0.0"
    name: str = "adapter@0.0"

    @abstractmethod
    def generate(self, problem: str) -> Response:
        """Run the brainstorming system and return a parsed Response.

        `problem` is the raw prompt string from problems/vN.yaml. Adapters
        must call `parse_ideas` (or something equivalent) on their raw output
        and populate `Response.ideas`.
        """


# ---------------------------------------------------------------------------
# idea parsing
# ---------------------------------------------------------------------------

# Matches leading bullets / numbering that adapters' outputs tend to produce.
# Order matters — try the more specific patterns first.
_BULLET_RE = re.compile(
    r"""^\s*(?:
          \d+\s*[.)]           # "1." or "1)"
        | [-*•]                # "- " or "* " or "• "
        | \(?[a-zA-Z]\s*[.)]   # "a." or "(a)"
    )\s+""",
    re.VERBOSE,
)

# Lines that are clearly structural, not ideas.
_SKIP_RE = re.compile(
    r"""^\s*(?:
          \#{1,6}\s            # markdown headings
        | (?:here(?:'s| are)|below)\b      # "Here are..." preambles
    )""",
    re.VERBOSE | re.IGNORECASE,
)


def parse_ideas(raw: str, origin: str | None = None) -> list[Idea]:
    """Split a verbatim brainstorming output into Ideas.

    Heuristic:
      1. If the text has bulleted / numbered lines, each is an idea.
      2. Otherwise, fall back to splitting on blank lines (paragraphs).
      3. Strip headings and obvious preamble lines ("Here are 10 ideas:").

    This is deliberately forgiving: downstream metrics (esp. flexibility)
    depend on a roughly reasonable split, not a perfect one.
    """
    if not raw or not raw.strip():
        return []

    lines = raw.splitlines()

    # --- pass 1: bullets / numbers ----------------------------------------
    bulleted: list[str] = []
    current: list[str] = []
    for line in lines:
        if _SKIP_RE.match(line):
            continue
        stripped = line.rstrip()
        if _BULLET_RE.match(stripped):
            if current:
                bulleted.append(" ".join(current).strip())
                current = []
            current.append(_BULLET_RE.sub("", stripped, count=1).strip())
        elif stripped.strip() == "":
            if current:
                bulleted.append(" ".join(current).strip())
                current = []
        else:
            # continuation of the current bullet, if any
            if current:
                current.append(stripped.strip())
    if current:
        bulleted.append(" ".join(current).strip())

    if len(bulleted) >= 2:
        return [Idea(text=t, origin=origin) for t in bulleted if t]

    # --- pass 2: paragraphs -----------------------------------------------
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    paragraphs = [p for p in paragraphs if not _SKIP_RE.match(p)]
    if len(paragraphs) >= 2:
        return [Idea(text=p, origin=origin) for p in paragraphs]

    # --- pass 3: single blob, split on sentences as a last resort ---------
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    if len(sentences) > 1:
        return [Idea(text=s, origin=origin) for s in sentences]

    return [Idea(text=raw.strip(), origin=origin)]
