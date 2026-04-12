---
description: Run pairwise LLM-judge battles between two saved runs and update Elo ratings.
argument-hint: <run-dir-a> <run-dir-b> [<battles-per-pair>]
---

Run blinded pairwise battles between two run directories that were produced by `/brainstormingbench:run` (or `bench run`).

**Arguments**
- `$1` — path to run directory A (e.g. `runs/plain-claude-20260412T...`)
- `$2` — path to run directory B
- `$3` — *(optional)* battles per problem; default 3

**What to do**

Run via Bash:

```bash
bench judge --a "$1" --b "$2" --battles "${3:-3}"
```

When finished:
1. Summarize the Elo table that `bench judge` prints.
2. Mention the saved `runs/battles-*.json` path so the user can re-aggregate later with `bench report`.
3. If the judge warned about model-family overlap (same family as generators), surface the warning and suggest changing `_JUDGE_MODEL` in `judge/pairwise.py` or using a different generator.
