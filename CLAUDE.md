# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

BrainstormingBench is a Claude Code plugin for evaluating brainstorming /
creativity systems. It runs blinded pairwise battles between any two
`/slash-command` systems and aggregates them into an Elo leaderboard with
bootstrap CIs. A separate researcher-only path computes four absolute
creativity-psychology metrics (fluency, flexibility, originality,
elaboration) over a run directory. See `README.md` for user-facing docs.

## Two-tier architecture

The repo has **two independent entry points** serving different audiences:

1. **Plugin path — stdlib only.** `plugin/scripts/bench.py` owns `run`,
   `battle`, `judge`, and `report`. It shells out to `claude -p` for both
   generators and judge and has no pip dependencies. The
   `/brainstormingbench:*` slash commands are thin wrappers over this
   script; users install the plugin and run immediately — no
   `pip install` required.

2. **Researcher path — pip-installed.** `cli.py` + `metrics/` exposes
   `bench metrics <run-dir>`, depending on numpy and sentence-transformers
   via `metrics/_embeddings.py`. This path is only needed for absolute
   metric scoring; it consumes run directories produced by the plugin
   path.

The two paths are deliberately decoupled: `metrics/` has no imports from
outside itself (see `metrics/_types.py` for the local `Response`/`Idea`
dataclasses that mirror the on-disk JSON shape written by `bench.py run`).
Changes to one path should not require changes in the other.

## Common commands

```bash
# researcher path only (plugin path needs no install)
pip install -e ".[dev]"

# run the test suite (offline — embeddings patched in conftest)
python -m pytest

# researcher CLI (metrics only)
python -m cli metrics runs/<dir>/ --baseline runs/<baseline_dir>/

# plugin CLI (stdlib — invoked by slash commands, runnable directly)
python3 plugin/scripts/bench.py run --skill /plain-claude --out runs/pc/
python3 plugin/scripts/bench.py battle --a /plain-claude --b /my-plugin:brainstorm --problem product-01
python3 plugin/scripts/bench.py judge --a runs/x/ --b runs/y/ --battles 3 --workers 4
python3 plugin/scripts/bench.py report
```

## Cross-file invariants to preserve

- **Judge ≠ generator family.** Generators use `claude-opus-4-6`
  (`GENERATOR_MODEL` in `plugin/scripts/bench.py`); the judge uses
  `claude-sonnet-4-6` (`JUDGE_MODEL`). Preserve this split — aggregate
  judgments across a shared family produce self-evaluation bias.
- **Position-normalization.** The judge sees responses in randomized A/B
  order per battle. Each `SingleBattle` records `order` ∈ {`A_first`,
  `B_first`}; `canonicalize()` uses this to flip verdicts back to the
  canonical A/B (= CLI `--a`/`--b`) before Elo processing. Any new
  aggregation code must respect `order`.
- **Model strings are exact.** `claude-opus-4-6` / `claude-sonnet-4-6`.
  No date suffixes.
- **`claude -p` transport.** Both generators and judge go through
  `claude_p()` in `plugin/scripts/bench.py`. Generator calls pass
  `--dangerously-skip-permissions` when `--allow-everything` is set
  (needed for skills that read their own technique files). Judge calls
  pair `--json-schema` with `--output-format json` and extract
  `.structured_output` from the envelope — `--json-schema` alone returns
  markdown.
- **Problem set lives with the plugin.** `plugin/scripts/problems/v1.json`
  is the canonical problem set; the researcher path doesn't own it. Since
  no historical benchmarks exist, v1 is editable; once results are
  published, add `v2.json` instead.
- **Rubric is frozen at the plugin.** `plugin/scripts/rubrics/rubric_v1.md`.
  Same versioning rule as the problem set.

## Testing notes

`tests/conftest.py` patches `metrics._embeddings.embed` with a
deterministic hashed-bag-of-words fake so the suite never pulls the real
sentence-transformers checkpoint over the network. Any new metric module
that imports `embed` directly (`from metrics._embeddings import embed`)
must also be added to the monkeypatch loop in `_patch_embed` — the loop
uses `importlib.import_module` because `metrics/__init__.py` re-exports
function names that shadow the submodule attributes.

## Claude Code plugin layout

- `.claude-plugin/marketplace.json` — exposes the repo to
  `/plugin marketplace add mgoldwasser/BrainstormingBench`. Its `source`
  field must point at a subdirectory (`./plugin`); the schema rejects a
  bare `.` even though the plugin is in the same repo.
- `plugin/.claude-plugin/plugin.json` — plugin manifest.
- `plugin/commands/*.md` — slash commands (`/brainstormingbench:battle`,
  `:run`, `:judge`, `:metrics`, `:leaderboard`). All wrap
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bench.py" <subcmd>`.
- `plugin/scripts/bench.py` — the stdlib plugin runner.
- `plugin/scripts/problems/v1.json`, `plugin/scripts/rubrics/rubric_v1.md`
  — frozen artifacts consumed by `bench.py`.
- `plugin/agents/brainstorm-runner.md` — subagent that runs a single
  brainstorming skill on a single problem. Designed to be spawned N-up
  in parallel from the main session.
- `plugin/skills/brainstorming-eval/SKILL.md` — auto-loads when the
  session is doing creativity benchmarking; primes Claude with the
  "pairwise > absolute, blind judging, frozen rubric" mental model.

When editing any of these:

- Slash commands and subagents must never brainstorm or judge themselves;
  they always defer to `bench.py <subcommand>`. Keeping this boundary
  clean is what makes the benchmark's results reproducible outside a
  Claude Code session.
- Any `/slash-command` string is accepted as a system spec by `bench.py`.
  The script passes the problem text as `$ARGUMENTS` via `claude -p`.
- `bench battle` writes `runs/battle-<ts>/{A,B}/*.json` and
  `runs/battle-<ts>/battle.json`, and prints a verdict summary.

## File layout (high signal only)

- `plugin/scripts/bench.py` — stdlib plugin runner; subcommands `run`,
  `battle`, `judge`, `report`. Hosts `claude_p()`, `parse_ideas()`,
  `canonicalize()`, `update_ratings()`, `bootstrap_cis()`,
  `parse_judge_envelope()`, `leaderboard_markdown()`.
- `metrics/_types.py` — local `Response`/`Idea` dataclasses; mirror the
  on-disk JSON so `load_response` parses any `bench.py`-produced file.
- `metrics/_embeddings.py` — singleton sentence-transformers loader; keep
  all network-touching code here so conftest can patch a single surface.
- `cli.py` — stdlib-only researcher CLI; exposes `bench metrics` only.
