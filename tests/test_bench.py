"""Stdlib tests for plugin/scripts/bench.py — the plugin runner.

These exercise the pure-data helpers (parsing, position-normalization,
Elo update, percentile, bootstrap) without touching `claude -p`. Any test
that would shell out to claude belongs in a live-integration file, not
here.

Imported via importlib because bench.py lives under `plugin/scripts/`
rather than a package on sys.path — that layout is intentional so the
plugin script stays drop-in runnable without `pip install`.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

_BENCH_PATH = Path(__file__).resolve().parent.parent / "plugin" / "scripts" / "bench.py"
_spec = importlib.util.spec_from_file_location("bench_plugin", _BENCH_PATH)
bench = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(bench)


# ---------------------------------------------------------------------------
# parse_ideas
# ---------------------------------------------------------------------------

class TestParseIdeas:
    def test_numbered_list(self) -> None:
        raw = "1. First idea\n2. Second idea\n3. Third idea"
        assert bench.parse_ideas(raw) == ["First idea", "Second idea", "Third idea"]

    def test_bulleted_list(self) -> None:
        raw = "- Alpha\n- Beta\n- Gamma"
        assert bench.parse_ideas(raw) == ["Alpha", "Beta", "Gamma"]

    def test_empty_input(self) -> None:
        assert bench.parse_ideas("") == []
        assert bench.parse_ideas("   \n\n  ") == []

    def test_single_idea_falls_back_to_text(self) -> None:
        # No list markers, single sentence → one idea.
        assert bench.parse_ideas("Just one thought.") == ["Just one thought."]

    def test_paragraph_split_when_no_bullets(self) -> None:
        raw = "First paragraph of an idea.\n\nSecond paragraph, separate idea."
        result = bench.parse_ideas(raw)
        assert len(result) == 2
        assert "First paragraph" in result[0]
        assert "Second paragraph" in result[1]

    def test_multiline_bullet_continuation(self) -> None:
        raw = "1. First idea\n   continuing on next line\n2. Second idea"
        result = bench.parse_ideas(raw)
        assert len(result) == 2
        assert "continuing on next line" in result[0]

    def test_strips_preamble_lines(self) -> None:
        # _SKIP_RE should drop meta lines like "Here are 10 ideas:".
        raw = "Here are some ideas:\n\n1. One\n2. Two"
        result = bench.parse_ideas(raw)
        assert result == ["One", "Two"]

    def test_single_bulleted_idea_is_one_idea_not_split_by_sentence(self) -> None:
        # Regression: "1. Long sentence. Another sentence." used to be
        # sentence-split into ["1.", "Long sentence.", ...] once the
        # bulleted list had only one item. A single bullet is a single idea.
        raw = "1. Turn the store into a book sommelier service bundled with a café partnership."
        assert bench.parse_ideas(raw) == [
            "Turn the store into a book sommelier service bundled with a café partnership."
        ]


# ---------------------------------------------------------------------------
# majority_winner — position-normalized
# ---------------------------------------------------------------------------

def _battle(order: str, winner: str) -> dict:
    return {"order": order, "output": {"winner": winner}}


class TestMajorityWinner:
    def test_all_A_wins_A_first(self) -> None:
        rec = {"battles": [_battle("A_first", "A"), _battle("A_first", "A")]}
        assert bench.majority_winner(rec) == "A"

    def test_position_flip_B_first(self) -> None:
        # Judge said "A" but A was shown second → canonical winner is B.
        rec = {"battles": [_battle("B_first", "A"), _battle("B_first", "A")]}
        assert bench.majority_winner(rec) == "B"

    def test_mixed_positions_consistent_canonical_winner(self) -> None:
        # Canonical A wins both: judge saw A_first+A, then B_first+B.
        rec = {
            "battles": [
                _battle("A_first", "A"),
                _battle("B_first", "B"),
            ]
        }
        assert bench.majority_winner(rec) == "A"

    def test_tie_when_split(self) -> None:
        rec = {
            "battles": [
                _battle("A_first", "A"),
                _battle("A_first", "B"),
            ]
        }
        assert bench.majority_winner(rec) == "tie"

    def test_ignores_malformed_verdicts(self) -> None:
        rec = {
            "battles": [
                _battle("A_first", "A"),
                {"order": "A_first", "output": {}},  # missing winner
                {"order": "A_first"},  # missing output
            ]
        }
        assert bench.majority_winner(rec) == "A"


# ---------------------------------------------------------------------------
# canonicalize
# ---------------------------------------------------------------------------

class TestCanonicalize:
    def test_A_first_A_wins(self) -> None:
        recs = [
            {
                "a_system": "sysA",
                "b_system": "sysB",
                "battles": [_battle("A_first", "A")],
            }
        ]
        assert bench.canonicalize(recs) == [("sysA", "sysB", 1.0)]

    def test_B_first_flips_score(self) -> None:
        # Judge picked "B" but sysA was shown second → canonical sysA wins.
        recs = [
            {
                "a_system": "sysA",
                "b_system": "sysB",
                "battles": [_battle("B_first", "B")],
            }
        ]
        assert bench.canonicalize(recs) == [("sysA", "sysB", 1.0)]

    def test_tie_scores_half(self) -> None:
        recs = [
            {
                "a_system": "sysA",
                "b_system": "sysB",
                "battles": [_battle("A_first", "tie")],
            }
        ]
        assert bench.canonicalize(recs) == [("sysA", "sysB", 0.5)]

    def test_skips_invalid_winners(self) -> None:
        recs = [
            {
                "a_system": "sysA",
                "b_system": "sysB",
                "battles": [
                    {"order": "A_first", "output": {"winner": "garbage"}},
                    _battle("A_first", "A"),
                ],
            }
        ]
        assert bench.canonicalize(recs) == [("sysA", "sysB", 1.0)]


# ---------------------------------------------------------------------------
# update_ratings — Elo mechanics
# ---------------------------------------------------------------------------

class TestUpdateRatings:
    def test_initial_unseen_systems_at_1500(self) -> None:
        ratings = bench.update_ratings([])
        assert ratings == {}

    def test_winner_gains_loser_loses(self) -> None:
        # Single battle, A beats B. Both start at 1500, so expected=0.5,
        # sa=1.0 → delta = K*0.5 = 16.
        ratings = bench.update_ratings([("A", "B", 1.0)], seed=0)
        assert ratings["A"] == pytest.approx(1500 + 16.0)
        assert ratings["B"] == pytest.approx(1500 - 16.0)

    def test_tie_no_movement_at_equal_ratings(self) -> None:
        ratings = bench.update_ratings([("A", "B", 0.5)], seed=0)
        assert ratings["A"] == pytest.approx(1500.0)
        assert ratings["B"] == pytest.approx(1500.0)

    def test_zero_sum(self) -> None:
        # Elo with fixed K is a zero-sum system: total rating conserved.
        battles = [("A", "B", 1.0), ("B", "C", 0.0), ("A", "C", 0.5)]
        ratings = bench.update_ratings(battles, seed=7)
        total = sum(ratings.values())
        assert total == pytest.approx(1500 * len(ratings))


# ---------------------------------------------------------------------------
# percentile
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_empty_is_nan(self) -> None:
        assert math.isnan(bench.percentile([], 50))

    def test_single_value(self) -> None:
        assert bench.percentile([42.0], 5) == 42.0
        assert bench.percentile([42.0], 99.99) == 42.0

    def test_exact_index(self) -> None:
        assert bench.percentile([10.0, 20.0, 30.0], 50) == 20.0

    def test_linear_interpolation(self) -> None:
        # p=25 on [0,10,20,30] → rank=0.75, interpolate between 0 and 10.
        assert bench.percentile([0.0, 10.0, 20.0, 30.0], 25) == pytest.approx(7.5)

    def test_endpoints(self) -> None:
        vals = [1.0, 2.0, 3.0, 4.0]
        assert bench.percentile(vals, 0) == 1.0
        assert bench.percentile(vals, 100) == 4.0


# ---------------------------------------------------------------------------
# bootstrap_cis
# ---------------------------------------------------------------------------

class TestBootstrapCIs:
    def test_empty_returns_initial_rating_bounds(self) -> None:
        # No battles → systems set is empty too; function returns empty dict.
        assert bench.bootstrap_cis([]) == {}

    def test_ci_deterministic_with_seed(self) -> None:
        battles = [("A", "B", 1.0)] * 10 + [("A", "B", 0.5)] * 2
        cis1 = bench.bootstrap_cis(battles, iterations=50, seed=123)
        cis2 = bench.bootstrap_cis(battles, iterations=50, seed=123)
        assert cis1 == cis2

    def test_ci_contains_point_estimate_loosely(self) -> None:
        # A dominates → A's CI should sit above 1500, B's below.
        battles = [("A", "B", 1.0)] * 20
        cis = bench.bootstrap_cis(battles, iterations=200, seed=42)
        lo_A, hi_A = cis["A"]
        lo_B, hi_B = cis["B"]
        assert lo_A > 1500 > hi_B
        assert lo_A <= hi_A and lo_B <= hi_B


# ---------------------------------------------------------------------------
# parse_judge_envelope
# ---------------------------------------------------------------------------

class TestParseJudgeEnvelope:
    def test_happy_path(self) -> None:
        envelope = {
            "is_error": False,
            "result": "unused",
            "structured_output": {"winner": "A", "rationale": "..."},
        }
        out = bench.parse_judge_envelope(json.dumps(envelope))
        assert out == {"winner": "A", "rationale": "..."}

    def test_is_error_raises(self) -> None:
        envelope = {"is_error": True, "result": "boom"}
        with pytest.raises(RuntimeError, match="error"):
            bench.parse_judge_envelope(json.dumps(envelope))

    def test_missing_structured_output_raises(self) -> None:
        envelope = {"is_error": False, "result": "markdown but no structured"}
        with pytest.raises(RuntimeError, match="structured_output"):
            bench.parse_judge_envelope(json.dumps(envelope))

    def test_non_dict_structured_output_raises(self) -> None:
        envelope = {"is_error": False, "structured_output": "not a dict"}
        with pytest.raises(RuntimeError, match="structured_output"):
            bench.parse_judge_envelope(json.dumps(envelope))


# ---------------------------------------------------------------------------
# auto_tag / system_name
# ---------------------------------------------------------------------------

class TestAutoTag:
    def test_slash_command(self) -> None:
        assert bench.auto_tag("/plain-claude") == "plain-claude"

    def test_namespaced_slash_command(self) -> None:
        # `:` is not in the safe-char set, so it collapses to `-`.
        assert bench.auto_tag("/my-plugin:brainstorm") == "my-plugin-brainstorm"

    def test_strips_args(self) -> None:
        assert bench.auto_tag("/foo:bar some text") == "foo-bar"


# ---------------------------------------------------------------------------
# leaderboard_markdown — smoke
# ---------------------------------------------------------------------------

def test_leaderboard_markdown_smoke() -> None:
    records = [
        {
            "a_system": "sysA",
            "b_system": "sysB",
            "problem_id": "p1",
            "battles": [
                _battle("A_first", "A"),
                _battle("B_first", "B"),  # canonical A wins
                _battle("A_first", "A"),
            ],
        }
    ]
    md = bench.leaderboard_markdown(records, seed=1)
    # A beats B 3-0; A should sort first in the table.
    lines = [l for l in md.splitlines() if "|" in l and "sys" in l]
    assert lines[0].startswith("| 1 |") and "sysA" in lines[0]
    assert "sysB" in lines[1]
