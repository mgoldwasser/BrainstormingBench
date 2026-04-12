"""Elo ratings from pairwise battle outcomes.

- Every system starts at 1500.
- K-factor = 32.
- Ties count as half a win for each side.
- Battles are processed in a caller-supplied (random) order; the order
  matters for Elo so the caller should seed its RNG for reproducibility.
- 95% bootstrap confidence intervals via battle-level resampling with
  replacement, 1000 iterations.

A "battle" for Elo purposes is one SingleBattle whose output contains a
valid `winner`. Ambiguous / errored battles are skipped.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from judge.pairwise import BattleRecord, SingleBattle

INITIAL = 1500.0
K = 32.0


# ---------------------------------------------------------------------------
# canonical (a, b, score_a) battle form
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CanonicalBattle:
    """One battle, with score expressed from a_system's perspective."""

    a_system: str
    b_system: str
    score_a: float  # 1.0 win, 0.5 tie, 0.0 loss


def canonicalize(records: Iterable[BattleRecord]) -> list[CanonicalBattle]:
    """Flatten BattleRecords into individual CanonicalBattles, order-normalized."""
    out: list[CanonicalBattle] = []
    for r in records:
        for b in r.battles:
            winner = b.output.get("winner")
            if winner not in ("A", "B", "tie"):
                continue
            # Normalize so "A" always refers to r.a_system.
            if b.order == "A_first":
                effective = winner
            else:
                effective = {"A": "B", "B": "A", "tie": "tie"}[winner]
            score = {"A": 1.0, "B": 0.0, "tie": 0.5}[effective]
            out.append(CanonicalBattle(r.a_system, r.b_system, score))
    return out


# ---------------------------------------------------------------------------
# Elo update
# ---------------------------------------------------------------------------

def update_ratings(
    battles: list[CanonicalBattle],
    initial: float = INITIAL,
    k: float = K,
    seed: int | None = None,
) -> dict[str, float]:
    """Process battles in random order, return final ratings.

    Returns: system_name -> final Elo rating.
    """
    rng = random.Random(seed)
    order = list(battles)
    rng.shuffle(order)

    ratings: dict[str, float] = {}
    for b in order:
        ra = ratings.setdefault(b.a_system, initial)
        rb = ratings.setdefault(b.b_system, initial)
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        eb = 1.0 - ea
        sa = b.score_a
        sb = 1.0 - sa
        ratings[b.a_system] = ra + k * (sa - ea)
        ratings[b.b_system] = rb + k * (sb - eb)
    return ratings


# ---------------------------------------------------------------------------
# bootstrap CI
# ---------------------------------------------------------------------------

def bootstrap_confidence_intervals(
    battles: list[CanonicalBattle],
    iterations: int = 1000,
    initial: float = INITIAL,
    k: float = K,
    seed: int = 42,
) -> dict[str, tuple[float, float]]:
    """Return (low, high) 95% CIs per system by resampling battles."""
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    systems: set[str] = set()
    for b in battles:
        systems.add(b.a_system)
        systems.add(b.b_system)

    samples: dict[str, list[float]] = {s: [] for s in systems}
    n = len(battles)
    if n == 0:
        return {s: (initial, initial) for s in systems}

    for it in range(iterations):
        idx = np_rng.integers(0, n, size=n)
        resampled = [battles[i] for i in idx]
        # Each bootstrap iteration gets its own shuffle seed so the order
        # effect is also integrated over.
        rated = update_ratings(resampled, initial=initial, k=k, seed=rng.randint(0, 2**32 - 1))
        for s in systems:
            samples[s].append(rated.get(s, initial))

    cis: dict[str, tuple[float, float]] = {}
    for s, vals in samples.items():
        arr = np.asarray(vals)
        lo, hi = np.percentile(arr, [2.5, 97.5])
        cis[s] = (float(lo), float(hi))
    return cis


# ---------------------------------------------------------------------------
# leaderboard struct
# ---------------------------------------------------------------------------

@dataclass
class LeaderboardEntry:
    system: str
    rating: float
    ci_low: float
    ci_high: float
    wins: int
    losses: int
    ties: int


@dataclass
class EloLeaderboard:
    entries: list[LeaderboardEntry] = field(default_factory=list)

    @classmethod
    def from_records(
        cls,
        records: Iterable[BattleRecord],
        seed: int = 42,
        bootstrap_iterations: int = 1000,
    ) -> "EloLeaderboard":
        battles = canonicalize(records)
        ratings = update_ratings(battles, seed=seed)
        cis = bootstrap_confidence_intervals(
            battles, iterations=bootstrap_iterations, seed=seed
        )

        # Win/loss/tie counts per system
        wlt: dict[str, list[int]] = {s: [0, 0, 0] for s in ratings}
        for b in battles:
            if b.score_a == 1.0:
                wlt[b.a_system][0] += 1
                wlt[b.b_system][1] += 1
            elif b.score_a == 0.0:
                wlt[b.a_system][1] += 1
                wlt[b.b_system][0] += 1
            else:
                wlt[b.a_system][2] += 1
                wlt[b.b_system][2] += 1

        entries = []
        for s, r in ratings.items():
            lo, hi = cis.get(s, (r, r))
            w, l, t = wlt.get(s, [0, 0, 0])
            entries.append(LeaderboardEntry(s, r, lo, hi, w, l, t))
        entries.sort(key=lambda e: e.rating, reverse=True)
        return cls(entries=entries)

    def to_markdown(self) -> str:
        lines = [
            "| Rank | System | Elo | 95% CI | W | L | T |",
            "|-----:|:-------|----:|:------:|--:|--:|--:|",
        ]
        for rank, e in enumerate(self.entries, start=1):
            ci = f"[{e.ci_low:.0f}, {e.ci_high:.0f}]"
            lines.append(
                f"| {rank} | `{e.system}` | {e.rating:.0f} | {ci} | "
                f"{e.wins} | {e.losses} | {e.ties} |"
            )
        return "\n".join(lines)
