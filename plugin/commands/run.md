---
description: Run a brainstorming skill/plugin against the full v1 problem set (30 prompts).
argument-hint: <slash-command> [<tag>]
---

Run a Claude Code brainstorming skill or plugin against BrainstormingBench's v1 problem set and save the responses to `runs/`.

**Arguments**
- `$1` — slash command for the system to evaluate, e.g. `/brainstorm-kit:brainstorm`.
- `$2` — *(optional)* a short tag for the run directory. Defaults to a sanitized form of the slash command.

**What to do**

Run the Bash command below. It invokes the skill once per problem via `claude -p` subprocesses; wall-clock time is ~3-5 minutes per problem for a typical multi-agent brainstorming system, so 30 problems with 4 workers runs ~25-40 min. Warn the user about runtime and subscription usage before starting.

```bash
tag="${2:-$(echo "$1" | sed -E 's#[^A-Za-z0-9._-]+#-#g; s#^-+|-+$##g')}"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bench.py" run \
  --skill "$1" \
  --out "runs/${tag}-$(date -u +%Y%m%dT%H%M%SZ)/" \
  --allow-everything \
  --workers 4
```

`--allow-everything` passes `--dangerously-skip-permissions` to each `claude -p` subprocess — required because non-interactive claude has no way to approve permission prompts at runtime.

`--workers 4` parallelizes across problems. Raise or lower based on how aggressively the target plugin fans out; too many workers can trigger subscription throttling.

When done, report:
1. How many problems completed successfully (check `runs/<dir>/*.json` count, expect 30 minus any skipped).
2. The `run_meta.json` path so the user can see the adapter tag, start time, and problem-set version.
3. Suggest `/brainstormingbench:judge` to battle this run against another, or `/brainstormingbench:leaderboard` to regenerate the leaderboard once at least two systems have runs.
