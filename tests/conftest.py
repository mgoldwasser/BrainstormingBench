"""Test fixtures.

Critical: we monkey-patch the embedding helper so the test suite never hits
the network to pull a sentence-transformers checkpoint. The fake embedding
is deterministic and keyword-sensitive enough to exercise the metrics logic
realistically.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import numpy as np
import pytest

# Make the repo root importable when running `pytest` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DIM = 32  # fake embedding dim; doesn't have to match the real model


def _fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic hashed bag-of-keywords embedding, L2-normalized.

    Each lowercased token hashes to a bucket; the vector is the normalized
    count over buckets. Texts with overlapping vocabulary end up similar;
    texts with disjoint vocabulary end up near-orthogonal.
    """
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    vecs = np.zeros((len(texts), DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for token in t.lower().split():
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            vecs[i, h % DIM] += 1.0
        norm = float(np.linalg.norm(vecs[i]))
        if norm > 0:
            vecs[i] /= norm
    return vecs


def _cosine_sim_matrix(v):
    return v @ v.T if v.shape[0] else np.zeros((0, 0), dtype=np.float32)


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    """Patch embeddings in every test; individual tests can re-patch if needed.

    `metrics/__init__.py` re-exports function names that shadow the submodule
    attributes on the `metrics` package, so we reach the modules via
    `importlib.import_module` rather than attribute access.
    """
    emb = importlib.import_module("metrics._embeddings")
    monkeypatch.setattr(emb, "embed", _fake_embed)
    monkeypatch.setattr(emb, "cosine_sim_matrix", _cosine_sim_matrix)

    for mod_name in ("metrics.fluency", "metrics.flexibility", "metrics.originality"):
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "embed"):
            monkeypatch.setattr(mod, "embed", _fake_embed)
        if hasattr(mod, "cosine_sim_matrix"):
            monkeypatch.setattr(mod, "cosine_sim_matrix", _cosine_sim_matrix)
    yield
