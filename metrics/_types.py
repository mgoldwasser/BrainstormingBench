"""Minimal Response/Idea types local to the metrics package.

Metrics used to import these from `adapters.base`, which coupled the
researcher metrics path to the old Python adapter layer. The adapter
layer was replaced by `plugin/scripts/bench.py` (stdlib, plugin-first);
this file breaks that dependency so `adapters/` can be deleted while
metrics/ keeps working unchanged.

The dataclasses intentionally mirror the on-disk JSON shape written by
`bench.py run`:

    {
      "problem_id": "...",
      "system":     "...",
      "ideas":      [{"text": "...", "origin": null}],
      "raw":        "...",
      "meta":       {...}
    }

so `load_response` can parse any run dir — plugin-produced or legacy —
without further conversion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Idea:
    text: str
    origin: str | None = None


@dataclass
class Response:
    problem_id: str
    system: str
    ideas: list[Idea]
    raw: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Response":
        return cls(
            problem_id=data["problem_id"],
            system=data["system"],
            ideas=[Idea(text=i["text"], origin=i.get("origin")) for i in data["ideas"]],
            raw=data.get("raw", ""),
            meta=data.get("meta") or {},
        )


def load_response(path: str | Path) -> Response:
    return Response.from_dict(json.loads(Path(path).read_text()))
