"""Judge tests: Elo math, battle canonicalization, aggregation."""

from __future__ import annotations

import random

import pytest

from adapters.base import Idea, Response
from judge.elo import (
    CanonicalBattle,
    EloLeaderboard,
    bootstrap_confidence_intervals,
    canonicalize,
    update_ratings,
)
from judge.pairwise import BattleRecord, PairwiseJudge, SingleBattle


# ---------------------------------------------------------------------------
# Elo arithmetic
# ---------------------------------------------------------------------------

def test_elo_equal_players_win_adds_16() -> None:
    # Two players at 1500 → expected 0.5. A win for A gives +32*(1-0.5) = +16.
    battles = [CanonicalBattle("A", "B", score_a=1.0)]
    ratings = update_ratings(battles, seed=0)
    assert ratings["A"] == pytest.approx(1516.0, abs=1e-6)
    assert ratings["B"] == pytest.approx(1484.0, abs=1e-6)


def test_elo_tie_leaves_equal_ratings_unchanged() -> None:
    battles = [CanonicalBattle("A", "B", score_a=0.5)]
    ratings = update_ratings(battles, seed=0)
    assert ratings["A"] == pytest.approx(1500.0)
    assert ratings["B"] == pytest.approx(1500.0)


def test_elo_deterministic_given_seed() -> None:
    battles = [
        CanonicalBattle("A", "B", 1.0),
        CanonicalBattle("A", "C", 1.0),
        CanonicalBattle("B", "C", 0.0),
        CanonicalBattle("A", "B", 0.5),
    ]
    r1 = update_ratings(battles, seed=42)
    r2 = update_ratings(battles, seed=42)
    assert r1 == r2


# ---------------------------------------------------------------------------
# canonicalization (position-normalization)
# ---------------------------------------------------------------------------

def _single(order, winner, a="A", b="B", pid="p") -> SingleBattle:
    return SingleBattle(
        a_system=a,
        b_system=b,
        problem_id=pid,
        order=order,
        output={"winner": winner, "novelty_winner": winner,
                "diversity_winner": winner, "usefulness_winner": winner,
                "reasoning": "x"},
        judge_model="claude-sonnet-4-6",
    )


def test_canonicalize_normalizes_b_first_order() -> None:
    rec = BattleRecord(
        a_system="A", b_system="B", problem_id="p",
        battles=[
            _single("A_first", "A"),   # A wins outright
            _single("B_first", "A"),   # "A" in B-first prompt == B in canonical
        ],
    )
    canon = canonicalize([rec])
    assert canon[0].score_a == 1.0
    assert canon[1].score_a == 0.0


def test_canonicalize_skips_errored_battles() -> None:
    rec = BattleRecord(
        a_system="A", b_system="B", problem_id="p",
        battles=[
            SingleBattle("A", "B", "p", "A_first",
                         {"error": "timeout"}, "claude-sonnet-4-6"),
            _single("A_first", "tie"),
        ],
    )
    canon = canonicalize([rec])
    assert len(canon) == 1
    assert canon[0].score_a == 0.5


# ---------------------------------------------------------------------------
# majority winner
# ---------------------------------------------------------------------------

def test_majority_winner_normalizes_order() -> None:
    rec = BattleRecord(
        a_system="A", b_system="B", problem_id="p",
        battles=[
            _single("A_first", "A"),
            _single("A_first", "A"),
            _single("B_first", "B"),  # in canonical: A wins
        ],
    )
    assert rec.majority_winner() == "A"


def test_majority_winner_ties_on_split() -> None:
    rec = BattleRecord(
        a_system="A", b_system="B", problem_id="p",
        battles=[
            _single("A_first", "A"),
            _single("A_first", "B"),
            _single("A_first", "tie"),
        ],
    )
    assert rec.majority_winner() == "tie"


# ---------------------------------------------------------------------------
# bootstrap CI
# ---------------------------------------------------------------------------

def test_bootstrap_ci_widens_with_fewer_battles() -> None:
    few = [CanonicalBattle("A", "B", 1.0)] * 3
    many = [CanonicalBattle("A", "B", 1.0)] * 100
    ci_few = bootstrap_confidence_intervals(few, iterations=200, seed=1)
    ci_many = bootstrap_confidence_intervals(many, iterations=200, seed=1)
    span_few = ci_few["A"][1] - ci_few["A"][0]
    span_many = ci_many["A"][1] - ci_many["A"][0]
    # More battles → tighter or equal CI on the dominant side.
    assert span_many <= span_few + 1e-6


def test_bootstrap_ci_empty_battles() -> None:
    ci = bootstrap_confidence_intervals([], iterations=100)
    assert ci == {}


# ---------------------------------------------------------------------------
# leaderboard
# ---------------------------------------------------------------------------

def test_leaderboard_ranks_by_rating() -> None:
    records = [
        BattleRecord("A", "B", "p1", [_single("A_first", "A")] * 5),
        BattleRecord("A", "C", "p2", [_single("A_first", "A")] * 5),
        BattleRecord("B", "C", "p3", [_single("A_first", "A")] * 5),
    ]
    board = EloLeaderboard.from_records(records, bootstrap_iterations=50)
    names = [e.system for e in board.entries]
    assert names == ["A", "B", "C"]
    md = board.to_markdown()
    assert "| 1 | `A` |" in md


# ---------------------------------------------------------------------------
# pairwise orchestration (with a fake client)
# ---------------------------------------------------------------------------

class _FakeClient:
    """Fake Anthropic client whose .messages.parse returns a canned verdict."""

    def __init__(self, verdict: str = "A") -> None:
        self._verdict = verdict
        self.messages = self._Messages(verdict)

    class _Messages:
        def __init__(self, verdict: str) -> None:
            self._verdict = verdict

        def parse(self, **kwargs):
            from judge.pairwise import JudgeOutput

            out = JudgeOutput(
                reasoning="fake",
                novelty_winner=self._verdict,
                diversity_winner=self._verdict,
                usefulness_winner=self._verdict,
                winner=self._verdict,
            )

            class _R:
                def __init__(self, o):
                    # Match the real SDK: messages.parse() returns an object
                    # whose validated Pydantic instance lives on .parsed_output.
                    self.parsed_output = o
            return _R(out)


def _resp(name: str, ideas: list[str]) -> Response:
    return Response(
        problem_id="p",
        system=name,
        ideas=[Idea(text=t) for t in ideas],
        raw="\n".join(ideas),
        meta={"model": "claude-opus-4-6"},
    )


def test_pairwise_api_transport_runs_n_battles_with_randomized_order() -> None:
    judge = PairwiseJudge(
        rng=random.Random(123),
        client=_FakeClient(verdict="A"),
        transport="api",
    )
    a = _resp("sys_a", ["alpha", "beta"])
    b = _resp("sys_b", ["gamma", "delta"])
    rec = judge.run(problem_text="problem", a=a, b=b, problem_id="p", battles=10)
    assert len(rec.battles) == 10
    orders = {b_.order for b_ in rec.battles}
    # With seed, we should see both positions in 10 draws.
    assert orders == {"A_first", "B_first"}


def test_pairwise_cli_transport_uses_injected_runner() -> None:
    """CLI transport: inject a fake `runner` callable instead of shelling out."""
    from judge.pairwise import JudgeOutput

    calls: list[dict] = []

    def fake_runner(system, user, output_format, model, effort):
        calls.append({
            "system_is_rubric": "FROZEN" in system or "blinded" in system.lower() or "rubric" in system.lower(),
            "user_has_both_responses": "Response A" in user and "Response B" in user,
            "output_format_is_pydantic": output_format is JudgeOutput,
            "model": model,
            "effort": effort,
        })
        return (
            output_format(
                reasoning="fake cli reasoning",
                novelty_winner="B",
                diversity_winner="B",
                usefulness_winner="B",
                winner="B",
            ),
            {"transport": "claude_cli", "model": model, "latency_s": 0.1},
        )

    judge = PairwiseJudge(
        rng=random.Random(0),
        transport="cli",
        runner=fake_runner,
    )
    a = _resp("sys_a", ["alpha"])
    b = _resp("sys_b", ["beta"])
    rec = judge.run(problem_text="problem", a=a, b=b, problem_id="p", battles=3)

    assert len(rec.battles) == 3
    assert len(calls) == 3
    # model is Sonnet per the judge default
    assert all(c["model"] == "claude-sonnet-4-6" for c in calls)
    assert all(c["effort"] == "medium" for c in calls)
    assert all(c["output_format_is_pydantic"] for c in calls)
    # each battle's output is the canned verdict, not an error
    for b_ in rec.battles:
        assert "error" not in b_.output
        assert b_.output["winner"] == "B"


def test_pairwise_flags_same_family_judge() -> None:
    # Judge sonnet vs generator sonnet → warning.
    a = Response("p", "s1", [Idea("x")], "x", meta={"model": "claude-sonnet-4-6"})
    b = Response("p", "s2", [Idea("y")], "y", meta={"model": "claude-opus-4-6"})
    judge = PairwiseJudge(
        judge_model="claude-sonnet-4-6",
        client=_FakeClient(),
        transport="api",
    )
    warnings = judge.check_family_disjoint(a, b)
    assert any("sonnet" in w for w in warnings)
