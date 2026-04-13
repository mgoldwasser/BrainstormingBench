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

## Installation

There are two pieces to install: the Python CLI (`bench`) and, optionally,
the Claude Code plugin that wraps it in slash commands. The plugin is a
thin UI over the CLI, so the CLI must be installed first.

### 1. Python CLI

Requires Python ≥ 3.10. **No Anthropic API key required** — by default the
benchmark routes every model call through the `claude` CLI
(`claude -p`), so auth is your Claude Code subscription.

```bash
git clone https://github.com/mgoldwasser/brainstormingbench.git
cd brainstormingbench

# recommended: isolate in a venv
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# editable install; drop [dev] if you don't need the tests
pip install -e ".[dev]"
```

Verify:

```bash
bench --help     # should list run / battle / metrics / judge / report
pytest -q        # should report "56 passed"
claude --help    # required for the default (subscription) transport
```

The `-e` (editable) install means `git pull` picks up new code without
reinstalling. If you skip the venv and install globally, make sure the
directory `pip` writes scripts to is on your `PATH` — `bench` must be
executable from any shell.

#### Transports: subscription vs API key

| Transport | Auth                     | When it's used                                                            |
| --------- | ------------------------ | ------------------------------------------------------------------------- |
| `cli` (default) | Claude Code subscription | Default if `claude` is on PATH; every generator and the judge shell out to `claude -p`. No API key touched. |
| `api`     | `ANTHROPIC_API_KEY`      | Opt-in via `BENCH_TRANSPORT=api`. Uses the Anthropic SDK directly — useful for CI / batch runs without a Claude Code install. |

Forced selection:

```bash
# force subscription (fails loudly if `claude` isn't on PATH)
export BENCH_TRANSPORT=cli

# force API key (fails loudly if ANTHROPIC_API_KEY isn't set)
export BENCH_TRANSPORT=api
export ANTHROPIC_API_KEY=sk-ant-...
```

If `BENCH_TRANSPORT` is unset, the benchmark picks `cli` when `claude` is on
PATH, otherwise `api`.

### 2. Claude Code plugin (optional)

Install the plugin to use `/brainstormingbench:battle`, `...:run`, etc.
from inside a Claude Code session. The plugin also ships a **subagent**
(`brainstorm-runner`) and a **skill** (`brainstorming-eval`) so the main
session can evaluate multiple systems in parallel — see "What you get"
below.

**Preferred: install via the plugin marketplace** (mirrors the
brainstorm-kit install UX):

```
/plugin marketplace add mgoldwasser/BrainstormingBench
/plugin install brainstormingbench@brainstormingbench
```

**Alternative: direct install from a local clone:**

```
/plugin install /absolute/path/to/brainstormingbench
```

**Alternative: direct install from git:**

```
/plugin install https://github.com/mgoldwasser/brainstormingbench.git
```

**Manual wiring**, if your Claude Code build doesn't expose `/plugin
install`, add an entry to `~/.claude/settings.json`:

```json
{
  "plugins": [
    { "path": "/absolute/path/to/brainstormingbench" }
  ]
}
```

Restart Claude Code after editing settings.

#### What you get after installing the plugin

- **Slash commands** (see the table in the next section) — the primary UI.
- **`brainstorm-runner` subagent** — invoke via the Agent tool to run one
  brainstorming skill on one problem. Spawn N in parallel to evaluate N
  systems without serializing their calls.
- **`brainstorming-eval` skill** — auto-loads when the session is working
  on creativity evaluation; gives Claude the benchmark's mental model
  (pairwise > absolute, blind judging, frozen rubric, etc.) without you
  having to re-explain it.

#### Sanity-check from a Claude Code session

```
!bench --help
```

If Click's help text prints, the plugin's slash commands will work. If you
see `bench: command not found`, the CLI isn't on the `PATH` Claude Code's
Bash tool uses — activate the venv in the shell that starts Claude Code,
or `pip install -e .` outside a venv so `bench` lands somewhere globally
visible.

#### End-to-end smoke test

```
/brainstormingbench:battle /brainstorm-kit:brainstorm plain_claude product-01
```

This runs both systems in fresh `claude -p` subprocesses, has a Sonnet
judge score them blind three times, and prints the verdict — typically
under a minute and well under \$1. No full 30-problem run required.

#### Parallel multi-system evaluation (subagent pattern)

Ask the session something like:

> Compare `/brainstorm-kit:brainstorm`, `/my-other-plugin:ideas`, and
> `plain_claude` on `product-01`. Run them in parallel, then judge.

With the `brainstorming-eval` skill loaded, Claude will spawn three
`brainstorm-runner` subagents concurrently (via the Agent tool), wait for
all three to finish, and then invoke `bench judge` or `bench battle` to
produce the verdict. Wall-time is the slowest single run, not the sum.

## Quickstart

```bash
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

# bonus: one-shot head-to-head on a single problem — fastest way to
# sanity-check a new brainstorming plugin before committing to a full run
bench battle --a "/my-plugin:ideas" --b "/brainstorm-kit:brainstorm" --problem product-01
```

A full evaluation of one system on the v1 seed set finishes in roughly 30
minutes of wall-time. With the default `cli` transport the spend is your
Claude Code subscription usage; with `BENCH_TRANSPORT=api` it runs under
\$20 on the Anthropic API.

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
| `/<plugin>:<command>` or `/<skill>`  | **generic Claude Code adapter** — any slash command becomes an adapter; shells out to `claude -p`. `{problem}` is appended automatically. |

### Benchmarking any Claude Code skill or plugin

If your brainstorming system is a Claude Code skill/plugin, you don't need
to write any Python. Just pass its slash command as the adapter spec:

```bash
bench run --adapter "/my-plugin:brainstorm" --out runs/my-plugin/
bench judge --a runs/my-plugin/ --b runs/plain-claude/ --battles 3
```

Under the hood this wraps `ClaudeSkillAdapter` (`adapters/claude_skill.py`),
which invokes `claude -p "<your-command> <problem-text>"` in a fresh
subprocess per problem.

## Claude Code plugin

BrainstormingBench also ships as a Claude Code plugin, so the whole flow
runs inside a live Claude Code session. Install the plugin (see Claude Code
plugin docs), then use any of:

| Slash command                                                           | What it does |
| ----------------------------------------------------------------------- | ------------ |
| `/brainstormingbench:battle <a-cmd> <b-cmd> <problem-id-or-text>`       | Blinded head-to-head between two skills on one problem, with verdict. |
| `/brainstormingbench:run <cmd> [tag]`                                   | Run a skill against the full v1 problem set.        |
| `/brainstormingbench:judge <run-a> <run-b> [battles]`                   | Pairwise Elo judging between two saved runs.        |
| `/brainstormingbench:metrics <run-dir> [baseline-dir]`                  | Absolute metrics over a saved run.                  |
| `/brainstormingbench:leaderboard`                                       | Regenerate and show `leaderboard.md`.               |

Quick example inside a Claude Code session:

```
/brainstormingbench:battle /brainstorm-kit:brainstorm /my-new-plugin:ideas tech-03
```

This runs both plugins on problem `tech-03` in fresh `claude -p` subprocesses,
has a Sonnet judge blindly score A vs B three times, and prints the verdict.

The single-problem battle is cheap (two generator calls + three judge calls,
~\$0.10–0.50 at typical prices) — good for quick iteration on a new
brainstorming plugin before committing to a full 30-problem run.

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
