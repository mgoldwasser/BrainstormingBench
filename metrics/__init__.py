"""Absolute (non-judge) metrics for brainstorming responses.

All metrics take a Response and return plain floats (or small dicts of
floats). They are deterministic given the same input and the same embedding
model; treat the embedding model as part of the metric's identity.

Metrics are diagnostic. The primary output of the benchmark is the Elo
leaderboard from pairwise LLM-judge battles (see judge/).
"""

from metrics.elaboration import elaboration
from metrics.flexibility import flexibility
from metrics.fluency import fluency
from metrics.originality import originality

__all__ = ["fluency", "flexibility", "originality", "elaboration"]
