# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

BrainstormingBench is a Python evaluation framework for brainstorming / creativity
systems. It scores black-box systems on four creativity-psychology metrics
(fluency, flexibility, originality, elaboration) and runs pairwise
LLM-judge battles that are aggregated into an Elo leaderboard with bootstrap
confidence intervals. See `README.md` for user-facing docs.

## Common commands

```bash
# install (editable, with dev deps)
pip install -e ".[dev]"

# run the test suite (offline — embeddings are patched in conftest)
pytest

# run a single test file / test
pytest tests/test_metrics.py
pytest tests/test_metrics.py::test_fluency_collapses_near_duplicates

# the CLI — entry point is cli.py at the repo root
python -m cli --help
bench run --adapter plain_claude --out runs/pc-$(date +%F)/
bench metrics runs/<dir>/ --baseline runs/<baseline_dir>/
bench judge --a runs/<a>/ --b runs/<b>/ --battles 3
bench report

# one-shot head-to-head (used by the /brainstormingbench:battle plugin command)
bench battle --a "/plugin-a:cmd" --b "/plugin-b:cmd" --problem product-01
```

`bench` is installed as a script (see `[project.scripts]` in
`pyproject.toml`). `python -m cli` works identically.

## Architecture in one paragraph

Each brainstorming system is wrapped in an `Adapter` (`adapters/base.py`).
An adapter's `generate(problem)` returns a `Response` containing `Idea`
objects parsed from verbatim raw output via `parse_ideas`. Running an
adapter over `problems/v1.yaml` produces a directory of per-problem JSON
files. `metrics/` consumes those files and emits absolute scores.
`judge/pairwise.py` runs blinded pairwise battles between two run
directories using a different Anthropic model family than the generators;
results are canonicalized (order-normalized so "A" always refers to the
first run directory) and fed into `judge/elo.py`, which produces the
markdown leaderboard.

## Cross-file invariants to preserve

- **Frozen files are frozen.** `problems/v1.yaml` and
  `judge/rubric_v1.md` must never be edited. If you need to change them,
  add `v2.yaml` / `rubric_v2.md` instead — historical runs pin the version
  they used, and comparability across runs depends on immutability.
- **No brainstorm-kit imports.** `adapters/brainstorm_kit.py` must only
  talk to the plugin externally (CLI subprocess or replicated SDK prompt).
  Never import brainstorm-kit code — the benchmark is explicitly
  tool-agnostic.
- **Judge ≠ generator family.** Generators use `claude-opus-4-6`; the
  judge uses `claude-sonnet-4-6` (see `_JUDGE_MODEL` in
  `judge/pairwise.py`). `PairwiseJudge.check_family_disjoint` warns when
  this invariant is violated at runtime.
- **Position-normalization.** The judge sees responses in randomized A/B
  order per battle. `SingleBattle.order` records which position the
  canonical `a_system` occupied; `judge/elo.canonicalize` uses this to
  flip verdicts back before Elo processing. Any new aggregation code must
  respect `order`.
- **Model strings are exact.** `claude-opus-4-6` / `claude-sonnet-4-6`.
  No date suffixes. Adaptive thinking (`thinking={"type": "adaptive"}`),
  no `budget_tokens`.

## Testing notes

`tests/conftest.py` patches `metrics._embeddings.embed` with a deterministic
hashed-bag-of-words fake so the suite never pulls the real
sentence-transformers checkpoint over the network. Any new metric module
that imports `embed` directly (`from metrics._embeddings import embed`)
must also be added to the monkeypatch loop in `_patch_embed` — note the
loop uses `importlib.import_module` because `metrics/__init__.py`
re-exports function names that shadow the submodule attributes.

Tests for the judge use a `_FakeClient` in `tests/test_judge.py` rather than
hitting the Anthropic API.

## Claude Code integration

The repo ships as a Claude Code plugin distributed via a single-plugin
marketplace:

- `.claude-plugin/marketplace.json` — exposes the repo to
  `/plugin marketplace add mgoldwasser/BrainstormingBench`. Its `source`
  field must point at a subdirectory (`./plugin`) — the schema rejects a
  bare `.` even though the plugin is in the same repo.
- `plugin/.claude-plugin/plugin.json` — plugin manifest.
- `plugin/commands/*.md` — slash commands (`/brainstormingbench:battle`,
  `:run`, `:judge`, `:metrics`, `:leaderboard`).
- `plugin/agents/brainstorm-runner.md` — subagent that runs a single
  brainstorming skill on a single problem. Designed to be spawned N-up
  in parallel from the main session for multi-system evaluations.
- `plugin/skills/brainstorming-eval/SKILL.md` — auto-loads when the
  session is working on creativity benchmarking; primes Claude with the
  "pairwise > absolute, blind judging, frozen rubric" mental model.

When editing any of these:

- Slash commands and subagents must never brainstorm or judge themselves;
  they always defer to `bench <subcommand>`. Keeping this boundary clean
  is what makes the benchmark's results reproducible outside a Claude Code
  session.
- The `ClaudeSkillAdapter` (`adapters/claude_skill.py`) is how arbitrary
  slash commands become benchmark adapters. `_build_adapter` auto-wraps
  anything starting with `/` into a `ClaudeSkillAdapter`. The template
  must contain `{problem}` (added automatically if absent).
- `bench battle` is the one-shot head-to-head used by
  `/brainstormingbench:battle`. It writes `runs/battle-<ts>/{A,B}/*.json`
  and `runs/battle-<ts>/battle.json`, and prints a verdict summary.
- The `brainstorm-runner` subagent takes `(skill, problem, out_dir)` and
  is deliberately a thin wrapper around `bench run` / `claude -p`. If you
  add features, add them to the CLI, not the subagent.

## File layout (high signal only)

- `adapters/base.py` — `Adapter` ABC, `Idea`, `Response`, and `parse_ideas`
  (bullets → numbered → paragraphs → sentence fallback).
- `adapters/claude_skill.py` — generic `/slash-command` adapter. Shells out
  to `claude -p` per problem; tests fake `subprocess.run`.
- `metrics/_embeddings.py` — singleton sentence-transformers loader.
  Keep all network-touching code here so conftest can patch a single
  surface.
- `judge/pairwise.py` — judge orchestration, Pydantic `JudgeOutput` schema,
  and family-disjoint sanity checks.
- `judge/elo.py` — canonicalization, Elo update, bootstrap CIs,
  `EloLeaderboard.to_markdown`.
- `cli.py` — Click group with `run`, `battle`, `metrics`, `judge`, `report`.
  Adapter spec parsing lives in `_build_adapter`.
- `.claude-plugin/marketplace.json` — marketplace manifest at repo root.
- `plugin/.claude-plugin/plugin.json` + `plugin/commands/*.md` — Claude
  Code plugin surface. Slash commands are thin wrappers over the CLI.
