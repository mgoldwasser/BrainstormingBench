"""Adapter that reads pre-written human responses from disk.

Directory layout expected:

    human_responses/
        product-01.txt
        product-02.txt
        ...

Each file contains the verbatim human response (bulleted, numbered, or prose).
`parse_ideas` handles the split.

A human adapter on the leaderboard is useful both as a control (is the
benchmark actually measuring creativity, or just verbosity?) and as an
upper bound.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapters.base import Adapter, Response, parse_ideas


class HumanAdapter(Adapter):
    """Replay pre-written human brainstorming responses."""

    def __init__(
        self,
        responses_dir: str | Path,
        author_tag: str = "anonymous",
    ) -> None:
        self._dir = Path(responses_dir)
        if not self._dir.is_dir():
            raise FileNotFoundError(f"human responses dir does not exist: {self._dir}")
        self._author_tag = author_tag
        self.name = f"human[{author_tag}]@0.1"

    def generate(self, problem: str) -> Response:
        # Human adapter is keyed on problem_id, not prompt text. The CLI
        # passes the problem_id via a side channel — see cli._run_adapter,
        # which sets self._current_problem_id before calling generate.
        problem_id = getattr(self, "_current_problem_id", None)
        if problem_id is None:
            raise RuntimeError(
                "HumanAdapter requires the caller to set _current_problem_id "
                "before generate(); the benchmark CLI does this automatically."
            )

        path = self._dir / f"{problem_id}.txt"
        if not path.exists():
            raise FileNotFoundError(
                f"no human response for {problem_id} at {path}"
            )

        started = time.time()
        raw = path.read_text()
        ideas = parse_ideas(raw, origin="human")
        return Response(
            problem_id="",  # filled in by the run harness
            system=self.name,
            ideas=ideas,
            raw=raw,
            meta={
                "author": self._author_tag,
                "source_path": str(path),
                "latency_s": round(time.time() - started, 4),
            },
        )
