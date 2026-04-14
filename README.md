# BrainstormingBench

An evaluation framework to test the creativity and brainstorming
capabilities of Claude Code skills and plugins.

BrainstormingBench treats each brainstorming system as a black box —
problem in, list of ideas out — and scores the output two ways:

1. **Pairwise LLM-judge battles** between systems, aggregated into an Elo
   leaderboard with bootstrap confidence intervals. This is the primary
   output.
2. **Absolute metrics** from creativity psychology: fluency, flexibility,
   originality, elaboration. These are diagnostic.

The repo is **independent of any specific brainstorming tool.** Any
`/slash-command` (a Claude Code skill, plugin command, or user command) is
accepted as a system. The benchmark shells out to `claude -p` for both
generation and judging; your Claude Code subscription is the only auth
needed.

## Two entry points

| Audience | Path | Install | What you get |
| --- | --- | --- | --- |
| Most users | **Claude Code plugin** | `/plugin install …` | `run`, `battle`, `judge`, `report` via `/brainstormingbench:*` slash commands. Stdlib only — no `pip`. |
| Researchers | **Python package** | `pip install -e ".[dev]"` | Adds `bench metrics <run-dir>` for absolute creativity metrics (needs numpy + sentence-transformers). |

The two paths are independent. The plugin writes run directories to disk;
the researcher CLI reads them back. If you only want Elo leaderboards,
you never need to `pip install` anything.

## Install the plugin

```
/plugin marketplace add mgoldwasser/BrainstormingBench
/plugin install brainstormingbench@brainstormingbench
```

Or install from a local clone:

```
/plugin install /absolute/path/to/BrainstormingBench
```

Once installed, five slash commands appear:

| Slash command | What it does |
| --- | --- |
| `/brainstormingbench:run <cmd> [tag]` | Run a skill against the v1 problem set (30 problems). |
| `/brainstormingbench:battle <a-cmd> <b-cmd> <problem>` | Blinded head-to-head between two skills on one problem. |
| `/brainstormingbench:judge <run-a> <run-b> [battles]` | Pairwise Elo judging over two saved runs. |
| `/brainstormingbench:leaderboard` | Regenerate and show `leaderboard.md`. |
| `/brainstormingbench:metrics <run-dir> [baseline-dir]` | Absolute creativity metrics (requires researcher install). |

Each one is a thin wrapper over `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bench.py"`,
so you can also run the script directly outside a Claude Code session.

## Quickstart — pairwise battles

```bash
# 1. run a baseline system on the full v1 problem set
python3 plugin/scripts/bench.py run --skill /plain-claude --out runs/plain-claude/

# 2. run a contender
python3 plugin/scripts/bench.py run \
    --skill /brainstorm-kit:brainstorm \
    --out runs/bk/ \
    --allow-everything \
    --workers 4

# 3. run pairwise battles, judged by Sonnet
python3 plugin/scripts/bench.py judge \
    --a runs/plain-claude/ \
    --b runs/bk/ \
    --battles 3 \
    --workers 4

# 4. regenerate leaderboard.md from all saved battles
python3 plugin/scripts/bench.py report

# bonus: single-problem head-to-head — fastest way to sanity-check a new plugin
python3 plugin/scripts/bench.py battle \
    --a /plain-claude \
    --b /my-plugin:brainstorm \
    --problem product-01
```

Flags of note:

- `--allow-everything` passes `--dangerously-skip-permissions` to the
  generator subprocess. Needed for plugins that read their own technique
  files or invoke tools at runtime.
- `--workers N` runs N `claude -p` subprocesses in parallel. Determinism
  is preserved (per-problem RNG derived from `(seed, problem_id)`), but
  watch for subscription rate limits.

## Quickstart — absolute metrics (researcher path)

Requires `pip install -e ".[dev]"` (brings in numpy, scikit-learn, hdbscan,
sentence-transformers).

```bash
# compute metrics for a run, using plain_claude as the "obvious ideas" baseline
bench metrics runs/bk/ --baseline runs/plain-claude/
```

Writes `runs/bk/metrics.json` with per-problem and aggregate values for:

- **Fluency** — distinct ideas after semantic dedup (cosine sim > 0.85).
- **Flexibility** — number of HDBSCAN clusters over idea embeddings.
- **Originality** — within-response (pairwise idea distance) and
  corpus-relative (distance to nearest neighbor in the baseline).
- **Elaboration** — mean tokens per idea plus a regex-based check for
  mechanism / example markers.

Embeddings use `sentence-transformers/all-MiniLM-L6-v2`. The test suite
patches this with a deterministic fake so tests run offline.

## Design principles

These are chosen deliberately; changing them silently breaks comparability.

- **Benchmark ≠ tool.** Nothing in this repo depends on a specific
  brainstorming system. Any `/slash-command` works.
- **Frozen versions.** `plugin/scripts/problems/v1.json` and
  `plugin/scripts/rubrics/rubric_v1.md` are immutable once results are
  published. New versions mean `v2` files, not edits.
- **Pairwise > absolute.** LLMs are unreliable absolute scorers but decent
  pairwise judges. The Elo leaderboard is the headline number.
- **Blind judging.** Judges never see system names. Responses are labeled
  "A" and "B" with randomized order per battle; `canonicalize()`
  flips verdicts back before Elo processing.
- **Different judge than generator family.** Generators use
  `claude-opus-4-6`; the judge uses `claude-sonnet-4-6`. Mixing families
  produces self-evaluation bias.
- **Cheap to re-run.** A full 30-problem evaluation of one system
  finishes in roughly 30 minutes at `--workers 4`.

## How a run flows

```
  plugin/scripts/problems/v1.json        /slash-command       metrics/
             │                                  │                │
             ▼                                  ▼                ▼
       [30 prompts] ── bench.py run ──► runs/<name>/*.json ── bench metrics
                                          │
                                          └─ bench.py judge (A vs B) ──► battles-*.json
                                                                             │
                                                                             ▼
                                                                   bench.py report
                                                                             │
                                                                             ▼
                                                                      leaderboard.md
```

Each `runs/<name>/` directory contains:

- one `<problem_id>.json` per problem (the skill's ideas, verbatim `raw`,
  and meta like latency)
- a `run_meta.json` with the skill spec and problem-set version
- optionally a `metrics.json` after `bench metrics` runs

Battle records live in `runs/battles-<timestamp>.json` and are consumed by
`bench.py report`.

## Subagent / parallel evaluation

The plugin ships a `brainstorm-runner` subagent and a `brainstorming-eval`
skill. With both loaded you can say:

> Compare `/brainstorm-kit:brainstorm`, `/my-other-plugin:ideas`, and
> `/plain-claude` on `product-01`. Run them in parallel, then judge.

Claude will spawn N `brainstorm-runner` subagents concurrently and then
call `bench judge`. Wall-time is the slowest single run, not the sum.

## Running the test suite

```bash
pip install -e ".[dev]"
pytest -q
```

The suite is offline: embeddings are monkey-patched with a hashed
bag-of-words fake, and no tests shell out to `claude -p`.

## Repository layout (high signal only)

- `plugin/scripts/bench.py` — stdlib plugin runner; subcommands `run`,
  `battle`, `judge`, `report`.
- `plugin/scripts/problems/v1.json` — frozen problem set.
- `plugin/scripts/rubrics/rubric_v1.md` — frozen judge rubric.
- `plugin/commands/*.md` — slash commands.
- `plugin/agents/brainstorm-runner.md` — parallel-evaluation subagent.
- `plugin/skills/brainstorming-eval/SKILL.md` — session-priming skill.
- `metrics/` — researcher-path creativity metrics (numpy,
  sentence-transformers).
- `metrics/_types.py` — local `Response`/`Idea` dataclasses; decouple
  metrics from the plugin.
- `cli.py` — `bench metrics` CLI (stdlib + metrics).

## What's not in scope

See [`FUTURE.md`](FUTURE.md) for ideas that were considered and deferred —
notably human-in-the-loop judging, more metrics, and cross-run cost
dashboards.

## License

MIT.
