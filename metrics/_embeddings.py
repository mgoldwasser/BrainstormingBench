"""Shared embedding utilities for metrics.

We use `sentence-transformers/all-MiniLM-L6-v2`: small, fast, good-enough
semantic similarity, and runs on CPU without fuss. The model is cached as a
module-level singleton so multi-metric runs don't re-load it per call.

Deterministic given the same inputs: sentence-transformers' encode is
deterministic for a given model checkpoint on a given device.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # avoid importing heavy deps at module import time
    from sentence_transformers import SentenceTransformer

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _model() -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def embed(texts: list[str]) -> np.ndarray:
    """Embed a list of strings. Returns an (N, D) float32 array, L2-normalized.

    Normalization means cosine similarity is just the dot product.
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    model = _model()
    vecs = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vecs.astype(np.float32, copy=False)


def cosine_sim_matrix(vecs: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity for an (N, D) L2-normalized matrix."""
    if vecs.shape[0] == 0:
        return np.zeros((0, 0), dtype=np.float32)
    return vecs @ vecs.T
