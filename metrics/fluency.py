"""Fluency: number of distinct ideas after semantic dedup.

Two ideas with cosine similarity > 0.85 on sentence embeddings are treated
as duplicates. This is stricter than string-identity (catches paraphrases)
but looser than requiring disjoint meaning.
"""

from __future__ import annotations

import numpy as np

from metrics._types import Response
from metrics._embeddings import cosine_sim_matrix, embed

DUPLICATE_THRESHOLD = 0.85


def fluency(response: Response, duplicate_threshold: float = DUPLICATE_THRESHOLD) -> float:
    """Return the count of distinct ideas as a float.

    Algorithm: greedy union-find over a cosine-similarity graph, thresholded
    at `duplicate_threshold`. Every connected component counts as one idea.
    """
    texts = [i.text for i in response.ideas if i.text.strip()]
    n = len(texts)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0

    vecs = embed(texts)
    sims = cosine_sim_matrix(vecs)

    # union-find
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if sims[i, j] >= duplicate_threshold:
                union(i, j)

    return float(len({find(i) for i in range(n)}))


def distinct_texts(
    response: Response, duplicate_threshold: float = DUPLICATE_THRESHOLD
) -> list[str]:
    """Return one representative text per duplicate cluster.

    Exposed for use by flexibility / originality, which should work over
    *distinct* ideas rather than raw adapter output.
    """
    texts = [i.text for i in response.ideas if i.text.strip()]
    n = len(texts)
    if n <= 1:
        return texts

    vecs = embed(texts)
    sims = cosine_sim_matrix(vecs)

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if sims[i, j] >= duplicate_threshold:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[ra] = rb

    seen: dict[int, int] = {}
    for idx in range(n):
        root = find(idx)
        if root not in seen:
            seen[root] = idx
    # preserve input order
    keep = sorted(seen.values())
    return [texts[i] for i in keep]


__all__ = ["fluency", "distinct_texts", "DUPLICATE_THRESHOLD"]
