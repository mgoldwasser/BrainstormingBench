"""Pairwise LLM-judge battles.

Given two Responses (A, B) to the same problem, run N blinded, position-
randomized battles and aggregate them into a single BattleRecord per pair.

Design notes:
  - The judge never sees system names. We label responses "A" and "B" at
    the point of the prompt.
  - A/B order is randomized per battle using a caller-supplied Random.
  - The judge uses a *different* model family from the generators: Sonnet
    when generators are Opus, or Opus when generators are Sonnet. The
    harness warns if this invariant is violated.
  - Structured output via `client.messages.parse` with a Pydantic schema.
"""

from __future__ import annotations

import os
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from adapters.base import Response


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------

Verdict = Literal["A", "B", "tie"]


class JudgeOutput(BaseModel):
    """Structured judge output. Keys match rubric_v1.md."""

    reasoning: str = Field(
        ..., description="3–8 sentence chain of thought, must precede verdicts."
    )
    novelty_winner: Verdict
    diversity_winner: Verdict
    usefulness_winner: Verdict
    winner: Verdict


@dataclass
class SingleBattle:
    """One run of the judge. `order` is the position the *A* system was in."""

    a_system: str
    b_system: str
    problem_id: str
    order: Literal["A_first", "B_first"]
    output: dict        # JudgeOutput dumped to dict, or {"error": "..."}
    judge_model: str


@dataclass
class BattleRecord:
    """Aggregated result of N battles for one (a, b, problem) triple."""

    a_system: str
    b_system: str
    problem_id: str
    battles: list[SingleBattle] = field(default_factory=list)

    # --- aggregation ------------------------------------------------------

    def majority_winner(self) -> Verdict:
        """Majority verdict across battles in canonical (a, b) orientation."""
        votes = {"A": 0, "B": 0, "tie": 0}
        for b in self.battles:
            w = b.output.get("winner")
            if w not in votes:
                continue
            # Position-normalize: if the battle ran with B first, its "A"
            # verdict refers to the b_system. We want votes relative to
            # a_system always being "A".
            if b.order == "A_first":
                votes[w] += 1
            else:
                # swap A<->B, leave "tie" alone
                if w == "A":
                    votes["B"] += 1
                elif w == "B":
                    votes["A"] += 1
                else:
                    votes["tie"] += 1
        top = max(votes.values())
        winners = [k for k, v in votes.items() if v == top]
        if len(winners) == 1:
            return winners[0]  # type: ignore[return-value]
        return "tie"

    def to_json(self) -> dict:
        return {
            "a_system": self.a_system,
            "b_system": self.b_system,
            "problem_id": self.problem_id,
            "battles": [asdict(b) for b in self.battles],
        }


# ---------------------------------------------------------------------------
# judge
# ---------------------------------------------------------------------------

_JUDGE_MODEL = "claude-sonnet-4-6"


def _load_rubric() -> str:
    rubric_path = Path(__file__).parent / "rubric_v1.md"
    return rubric_path.read_text()


def _render_response(r: Response) -> str:
    """Render a Response for the judge — ideas only, no system name."""
    lines = []
    for i, idea in enumerate(r.ideas, start=1):
        lines.append(f"{i}. {idea.text.strip()}")
    return "\n".join(lines) if lines else "(no ideas)"


def _build_user_prompt(problem_text: str, a_text: str, b_text: str) -> str:
    return (
        f"Problem:\n{problem_text}\n\n"
        f"--- Response A ---\n{a_text}\n\n"
        f"--- Response B ---\n{b_text}\n\n"
        "Follow the rubric. Return JSON matching the required schema."
    )


class PairwiseJudge:
    def __init__(
        self,
        judge_model: str = _JUDGE_MODEL,
        rng: random.Random | None = None,
        client=None,  # injectable for tests
    ) -> None:
        self._judge_model = judge_model
        self._rng = rng or random.Random()
        self._client = client
        self._rubric = _load_rubric()

    # ------------------------------------------------------------------
    # sanity checks
    # ------------------------------------------------------------------

    def check_family_disjoint(self, a: Response, b: Response) -> list[str]:
        """Warn if the judge shares a model family with either generator."""
        warnings: list[str] = []
        judge_family = _family(self._judge_model)
        for resp in (a, b):
            model = resp.meta.get("model")
            if model and _family(model) == judge_family:
                warnings.append(
                    f"judge model family ({judge_family}) matches generator "
                    f"{resp.system}'s model {model}; results may be biased"
                )
        return warnings

    # ------------------------------------------------------------------
    # single battle
    # ------------------------------------------------------------------

    def _run_one(
        self,
        problem_text: str,
        a: Response,
        b: Response,
        problem_id: str,
    ) -> SingleBattle:
        a_first = self._rng.random() < 0.5
        order: Literal["A_first", "B_first"] = "A_first" if a_first else "B_first"
        first, second = (a, b) if a_first else (b, a)
        user = _build_user_prompt(
            problem_text=problem_text,
            a_text=_render_response(first),
            b_text=_render_response(second),
        )

        client = self._client or _default_client()

        try:
            result = client.messages.parse(
                model=self._judge_model,
                max_tokens=4096,
                system=self._rubric,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                response_format=JudgeOutput,
                messages=[{"role": "user", "content": user}],
            )
            parsed: JudgeOutput = result.output
            output_dict = parsed.model_dump()
        except Exception as e:  # noqa: BLE001 — we record the failure and move on
            output_dict = {"error": f"{type(e).__name__}: {e}"}

        return SingleBattle(
            a_system=a.system,
            b_system=b.system,
            problem_id=problem_id,
            order=order,
            output=output_dict,
            judge_model=self._judge_model,
        )

    # ------------------------------------------------------------------
    # N battles → BattleRecord
    # ------------------------------------------------------------------

    def run(
        self,
        problem_text: str,
        a: Response,
        b: Response,
        problem_id: str,
        battles: int = 3,
    ) -> BattleRecord:
        record = BattleRecord(
            a_system=a.system, b_system=b.system, problem_id=problem_id
        )
        for _ in range(battles):
            record.battles.append(
                self._run_one(problem_text, a, b, problem_id)
            )
        return record


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _family(model: str) -> str:
    """'opus', 'sonnet', 'haiku', or the raw string if unknown."""
    for fam in ("opus", "sonnet", "haiku"):
        if fam in model:
            return fam
    return model


def _default_client():
    from anthropic import Anthropic

    return Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
