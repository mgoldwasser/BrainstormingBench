---
description: Run a brainstorming skill/plugin against the full v1 problem set (30 prompts).
argument-hint: <slash-command> [<tag>]
---

Run a Claude Code brainstorming skill or plugin against BrainstormingBench's v1 problem set and save the responses to `runs/`.

**Arguments**
- `$1` — slash command for the system to evaluate, e.g. `/brainstorm-kit:brainstorm`. `{problem}` is appended automatically if missing.
- `$2` — *(optional)* a short tag for the run directory. Defaults to a sanitized form of the command.

**What to do**

Run the Bash command below. This will invoke the skill 30 times (once per problem) via `claude -p`, which is slow and costs API credit — warn me before running if the user has not already confirmed.

```bash
tag="${2:-$(echo "$1" | sed -E 's#[^A-Za-z0-9._-]+#-#g; s#^-+|-+$##g')}"
bench run --adapter "$1" --out "runs/${tag}-$(date -u +%Y%m%dT%H%M%SZ)/"
```

When done, report:
1. How many problems completed successfully (check `runs/<dir>/*.json` count, expect 30).
2. Any adapter errors surfaced in `run_meta.json` or stderr.
3. Suggest running `/brainstormingbench:judge` to battle this run against another, or `/brainstormingbench:leaderboard` to regenerate the leaderboard.
