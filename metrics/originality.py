"""Originality: how novel the ideas are, on two axes.

1. Within-response originality — mean pairwise cosine distance between this
   response's ideas. High value = ideas are far apart from each other
   (a response full of near-duplicates scores low).

2. Corpus-relative originality — mean cosine distance from each of this
   response's ideas to its nearest neighbor in a fixed "obvious ideas"
   corpus. Higher = more novel relative to what a baseline system would
   have produced for the same prompt family.

The corpus is built from `plain_claude` runs on the same problem set; see
`build_obvious_corpus`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from adapters.base import Response
from metrics._embeddings import embed
from metrics.fluency import distinct_texts


# ---------------------------------------------------------------------------
# within-response
# ---------------------------------------------------------------------------

def within_response_originality(response: Response) -> float:
    texts = distinct_texts(response)
    if len(texts) < 2:
        return 0.0
    vecs = embed(texts)
    sims = vecs @ vecs.T
    n = sims.shape[0]
    # mean over upper triangle (i < j)
    iu = np.triu_indices(n, k=1)
    mean_sim = float(np.mean(sims[iu]))
    # cosine distance = 1 - cosine similarity; distances live in [0, 2]
    return 1.0 - mean_sim


# ---------------------------------------------------------------------------
# corpus-relative
# ---------------------------------------------------------------------------

def build_obvious_corpus(responses: list[Response]) -> np.ndarray:
    """Build an (N, D) embedding matrix from a list of baseline responses.

    Typically the baseline is `plain_claude`. All ideas across all problems
    are pooled into a single corpus — the intuition being "ideas the
    frontier model reaches for by default, on *any* prompt in this family".
    """
    all_texts: list[str] = []
    for r in responses:
        all_texts.extend(distinct_texts(r))
    if not all_texts:
        return np.zeros((0, 384), dtype=np.float32)
    return embed(all_texts)


def corpus_relative_originality(
    response: Response, corpus_embeddings: np.ndarray
) -> float:
    """Mean cosine distance from each idea to its nearest corpus neighbor."""
    if corpus_embeddings.shape[0] == 0:
        return 0.0
    texts = distinct_texts(response)
    if not texts:
        return 0.0
    vecs = embed(texts)
    sims = vecs @ corpus_embeddings.T  # (n_ideas, n_corpus)
    nearest = sims.max(axis=1)         # highest similarity per idea
    distances = 1.0 - nearest
    return float(np.mean(distances))


# ---------------------------------------------------------------------------
# combined
# ---------------------------------------------------------------------------

def originality(
    response: Response,
    corpus_embeddings: np.ndarray | None = None,
) -> dict[str, float]:
    """Return both originality numbers as a small dict.

    If `corpus_embeddings` is None (or empty), `corpus_relative` is reported
    as NaN so downstream code can distinguish "0 novelty" from "no corpus".
    """
    within = within_response_originality(response)
    if corpus_embeddings is None or corpus_embeddings.shape[0] == 0:
        corpus_rel = float("nan")
    else:
        corpus_rel = corpus_relative_originality(response, corpus_embeddings)
    return {"within_response": within, "corpus_relative": corpus_rel}


__all__ = [
    "originality",
    "within_response_originality",
    "corpus_relative_originality",
    "build_obvious_corpus",
]
