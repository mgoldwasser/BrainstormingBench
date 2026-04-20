"""Metric tests. Embeddings are patched in conftest to a deterministic fake.

The fake embedding shares buckets for overlapping tokens, so ideas with
shared vocabulary look similar and ideas with disjoint vocabulary look
distant — which is what the metrics fundamentally rely on.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from metrics._types import Idea, Response
from metrics.elaboration import elaboration
from metrics.fluency import distinct_texts, fluency
from metrics.originality import (
    build_obvious_corpus,
    corpus_relative_originality,
    originality,
    within_response_originality,
)


def _resp(ideas: list[str]) -> Response:
    return Response(
        problem_id="p",
        system="sys@0.1",
        ideas=[Idea(text=t) for t in ideas],
        raw="\n".join(ideas),
        meta={},
    )


# ---------------------------------------------------------------------------
# fluency
# ---------------------------------------------------------------------------

def test_fluency_empty() -> None:
    assert fluency(_resp([])) == 0.0


def test_fluency_counts_distinct() -> None:
    r = _resp([
        "alpha beta gamma",
        "delta epsilon zeta",
        "eta theta iota",
    ])
    assert fluency(r) == 3.0


def test_fluency_collapses_near_duplicates() -> None:
    # Three texts with the same vocabulary → identical normalized embeddings →
    # cosine sim = 1.0 → all collapse into one cluster.
    r = _resp([
        "alpha beta gamma",
        "alpha beta gamma",
        "alpha beta gamma",
    ])
    assert fluency(r) == 1.0


def test_distinct_texts_keeps_first_per_cluster() -> None:
    r = _resp(["alpha beta", "alpha beta", "delta epsilon"])
    out = distinct_texts(r)
    assert out == ["alpha beta", "delta epsilon"]


# ---------------------------------------------------------------------------
# flexibility
# ---------------------------------------------------------------------------

def test_flexibility_non_empty_returns_positive_int(monkeypatch) -> None:
    """Flexibility returns >= 1 for any non-empty response.

    HDBSCAN behavior on low-dimensional fake embeddings is hard to pin down,
    so this test locks down the invariants (positive, integer-valued) rather
    than specific cluster counts.
    """
    pytest.importorskip("hdbscan")
    from metrics.flexibility import flexibility

    r = _resp([
        "alpha beta gamma",
        "delta epsilon zeta",
        "eta theta iota",
        "kappa lambda mu",
    ])
    val = flexibility(r)
    assert val >= 1.0
    assert val == int(val)  # cluster count is integer-valued


def test_flexibility_noise_points_count_as_singletons(monkeypatch) -> None:
    """When HDBSCAN labels everything as noise, every point is a singleton."""
    pytest.importorskip("hdbscan")
    import importlib
    flex_mod = importlib.import_module("metrics.flexibility")

    class _AllNoise:
        def __init__(self, **kwargs): pass
        def fit_predict(self, X):
            return np.full(X.shape[0], -1, dtype=int)

    # inject a fake HDBSCAN into the module's hdbscan reference
    import types
    fake = types.SimpleNamespace(HDBSCAN=_AllNoise)
    monkeypatch.setitem(__import__("sys").modules, "hdbscan", fake)

    r = _resp(["a", "b", "c", "d"])
    assert flex_mod.flexibility(r) == 4.0


def test_flexibility_single_idea_is_one() -> None:
    pytest.importorskip("hdbscan")
    from metrics.flexibility import flexibility

    assert flexibility(_resp(["alpha beta gamma"])) == 1.0


# ---------------------------------------------------------------------------
# originality
# ---------------------------------------------------------------------------

def test_within_response_originality_ranges() -> None:
    # identical ideas → within == 0
    same = _resp(["alpha beta", "alpha beta", "alpha beta"])
    assert within_response_originality(same) == pytest.approx(0.0, abs=1e-6)

    # after dedup, only one idea remains → within == 0 (cannot be original vs self)
    # so test with genuinely distinct sets.
    mixed = _resp(["alpha beta", "delta epsilon", "eta theta"])
    assert within_response_originality(mixed) > 0.5


def test_corpus_relative_originality() -> None:
    baseline = [_resp(["alpha beta gamma", "delta epsilon zeta"])]
    corpus = build_obvious_corpus(baseline)
    assert corpus.shape[0] == 2

    # Response whose ideas overlap the corpus → low novelty.
    similar = _resp(["alpha beta gamma"])
    similar_score = corpus_relative_originality(similar, corpus)

    # Response whose ideas are disjoint from the corpus → high novelty.
    novel = _resp(["omega pi rho"])
    novel_score = corpus_relative_originality(novel, corpus)

    assert novel_score > similar_score


def test_originality_reports_nan_without_corpus() -> None:
    r = _resp(["alpha beta", "gamma delta"])
    result = originality(r, corpus_embeddings=None)
    assert math.isnan(result["corpus_relative"])
    assert result["within_response"] > 0.0


# ---------------------------------------------------------------------------
# elaboration
# ---------------------------------------------------------------------------

def test_elaboration_token_count() -> None:
    r = _resp(["one two three", "four five"])
    result = elaboration(r)
    assert result["mean_tokens_per_idea"] == pytest.approx(2.5)


def test_elaboration_detects_mechanism() -> None:
    r = _resp([
        "Do X because the cost is lower.",
        "Do Y by restructuring the team.",
        "Do Z, no justification.",
    ])
    result = elaboration(r)
    assert result["mechanism_coverage"] == pytest.approx(2 / 3)


def test_elaboration_detects_examples() -> None:
    r = _resp([
        "Try a rotating cast, e.g. weekly guest hosts.",
        "Swap the format, for example to a listener-driven Q&A.",
        "Re-edit older episodes.",
    ])
    result = elaboration(r)
    assert result["example_coverage"] == pytest.approx(2 / 3)
    assert result["any_justification_coverage"] >= result["example_coverage"]


def test_elaboration_empty_response() -> None:
    result = elaboration(_resp([]))
    assert result["mean_tokens_per_idea"] == 0.0
    assert result["mechanism_coverage"] == 0.0
