# BrainstormingBench

An evaluation framework to test the creativity and brainstorming capabilities
of AI systems.

BrainstormingBench treats each brainstorming system as a black box — problem
in, list of ideas out — and scores the output two ways:

1. **Absolute metrics** from creativity psychology: fluency, flexibility,
   originality, elaboration. These are diagnostic.
2. **Pairwise LLM-judge battles** between systems, aggregated into an Elo
   leaderboard with bootstrap confidence intervals. This is the primary
   output.

The repo is **independent of any specific brainstorming tool.** Tools are
plugged in via the [`Adapter`](adapters/base.py) interface, and the
`brainstorm_kit` adapter (for
[github.com/mgoldwasser/ClaudeBrainstorming](https://github.com/mgoldwasser/ClaudeBrainstorming))
talks to that plugin externally — nothing in this repo imports it.

## Quickstart

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...

# 1. run a baseline adapter on the v1 problem set (30 problems)
bench run --adapter plain_claude --out runs/plain-claude-2026-04-12/

# 2. run a contender
bench run --adapter brainstorm_kit --out runs/bk-2026-04-12/

# 3. compute absolute metrics (using plain_claude as the "obvious ideas" baseline)
bench metrics runs/bk-2026-04-12/ --baseline runs/plain-claude-2026-04-12/

# 4. run pairwise battles
bench judge --a runs/plain-claude-2026-04-12/ --b runs/bk-2026-04-12/ --battles 3

# 5. regenerate the leaderboard from all saved battles
bench report
```

A full evaluation of one system on the v1 seed set should cost under \$20
and finish in under 30 minutes on the Anthropic API.

## Design principles

These are chosen deliberately; changing them silently breaks comparability.

- **Benchmark ≠ tool.** Nothing in this repo depends on brainstorm-kit or any
  other tool. Adapters talk to their systems externally.
- **Frozen versions.** `problems/v1.yaml` and `judge/rubric_v1.md` are
  immutable once released. New versions mean `v2` files, not edits.
- **Pairwise > absolute.** LLMs are unreliable absolute scorers but decent
  pairwise judges. The Elo leaderboard is the headline number.
- **Blind judging.** Judges never see system names. Responses are labeled
  "A" and "B" with randomized order per battle.
- **Different judge than generator.** Generators use Opus, the judge uses
  Sonnet (or vice-versa). The judge warns when family overlap is detected.
- **Cheap to re-run.** See the \$20 / 30-minute target above.

## How a run flows

```
  problems/v1.yaml             adapter                     metrics/
       │                          │                           │
       ▼                          ▼                           ▼
   [30 prompts] ── bench run ──► runs/<name>/*.json ── bench metrics
                                  │
                                  └─── bench judge (A vs B) ──► battle records
                                                                     │
                                                                     ▼
                                                              bench report
                                                                     │
                                                                     ▼
                                                              leaderboard.md
```

Each `runs/<name>/` directory contains:

- one `<problem_id>.json` per problem (the adapter's `Response`, with
  `ideas`, verbatim `raw`, and meta like latency / token counts)
- a `run_meta.json` with adapter name and problem-set version
- a `metrics.json` after `bench metrics` runs

Battle records live in `runs/battles-<timestamp>.json` and are consumed by
`bench report`.

## Writing a new adapter

An adapter is 30–50 lines. Implement `Adapter` from
[`adapters/base.py`](adapters/base.py):

```python
from adapters.base import Adapter, Response, parse_ideas

class MyAdapter(Adapter):
    name = "my_adapter@0.1"   # immutable; includes version

    def generate(self, problem: str) -> Response:
        raw = call_my_brainstorming_system(problem)   # any I/O you want
        return Response(
            problem_id="",     # the CLI fills this in
            system=self.name,
            ideas=parse_ideas(raw),   # shared parser handles bullets / numbers
            raw=raw,
            meta={"latency_s": ..., "model": "..."},
        )
```

Then register it in `cli._build_adapter` so `--adapter my_adapter` works.
That's the entire contract: the benchmark never reaches inside your system.

## Adapters shipped with the repo

| Adapter                              | What it is                                                      |
| ------------------------------------ | --------------------------------------------------------------- |
| `plain_claude`                       | baseline: one Claude Opus call, "brainstorm 10 ideas for X"     |
| `single_technique[<name>]`           | baseline: one Opus call in a specific technique (stoner_circle, first_principles, worst_idea) |
| `brainstorm_kit[auto\|cli\|sdk]`     | external adapter for the brainstorm-kit plugin; picks transport automatically |
| `human:/path/to/responses_dir/`      | replay pre-written human responses for control / upper-bound    |

## Metrics, briefly

All four metrics operate on a single `Response` and are deterministic given
the same embedding model (`sentence-transformers/all-MiniLM-L6-v2`).

- **Fluency** — count of distinct ideas after semantic dedup (cosine
  similarity > 0.85).
- **Flexibility** — number of semantic clusters via HDBSCAN over idea
  embeddings; noise points count as singleton clusters.
- **Originality** — within-response (mean pairwise distance between ideas)
  and corpus-relative (mean distance to nearest neighbor in a "obvious
  ideas" corpus built from a baseline run, typically `plain_claude`).
- **Elaboration** — mean tokens per idea plus a regex-based check for
  mechanism / example markers ("because", "by ...", "e.g.", "for example").

## Judge, briefly

`judge/pairwise.py` runs N=3 blinded, position-randomized battles per pair
per problem. The judge reads `judge/rubric_v1.md` (frozen), receives A and
B as ideas-only (no system names), and returns a structured verdict via
`client.messages.parse()` with the `JudgeOutput` Pydantic schema.

`judge/elo.py` folds battle records into Elo ratings (K = 32, initial 1500,
ties = half-win each). 95% confidence intervals come from 1000 bootstrap
resamples over battles, re-running the full Elo update each time.

## Running the test suite

```bash
pytest
```

Tests patch the sentence-transformers embedding with a deterministic
hashed-bag-of-words fake, so the suite runs offline and in a couple of
seconds. HDBSCAN is the only heavy dependency exercised by tests.

## What's not in scope

See [`FUTURE.md`](FUTURE.md) for ideas that were considered and deferred —
notably human-in-the-loop judging, more metrics, and cross-run cost
dashboards.

## License

MIT.
