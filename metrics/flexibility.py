"""Flexibility: number of distinct semantic clusters in the idea set.

Counts HDBSCAN clusters over idea embeddings. Noise points (label == -1)
are treated as singletons, each contributing 1 to the count — a response
of 10 totally-unrelated ideas should score higher on flexibility than a
response of 10 variations on a theme.
"""

from __future__ import annotations

import numpy as np

from metrics._types import Response
from metrics._embeddings import embed
from metrics.fluency import distinct_texts


def flexibility(response: Response, min_cluster_size: int = 2) -> float:
    """Return the number of semantic clusters."""
    texts = distinct_texts(response)
    n = len(texts)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0

    vecs = embed(texts)

    # HDBSCAN on cosine-ish distance; using euclidean on L2-normalized vectors
    # is equivalent up to a monotone transform, and the hdbscan package's
    # default metric is euclidean, which avoids a dependency pin on a specific
    # metric backend.
    import hdbscan

    # With small N, HDBSCAN struggles. Use a safe floor.
    effective_min = max(2, min(min_cluster_size, max(2, n // 4)))
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=effective_min,
        metric="euclidean",
        allow_single_cluster=True,
    )
    labels = clusterer.fit_predict(vecs.astype(np.float64))

    cluster_count = len({lbl for lbl in labels if lbl != -1})
    noise_count = int(np.sum(labels == -1))

    # Every noise point is its own singleton cluster for the purposes of
    # flexibility.
    return float(cluster_count + noise_count)


__all__ = ["flexibility"]
