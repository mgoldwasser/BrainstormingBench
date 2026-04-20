---
description: Run pairwise LLM-judge battles between two saved runs and update Elo ratings.
argument-hint: <run-dir-a> <run-dir-b> [<battles-per-pair>]
---

Run blinded pairwise battles between two run directories previously produced by `/brainstormingbench:run`.

**Arguments**
- `$1` — path to run directory A (e.g. `runs/brainstorm-kit-20260414T...`)
- `$2` — path to run directory B
- `$3` — *(optional)* battles per problem; default 3

**What to do**

Run via Bash. The script judges every problem id that appears in both run directories, using the Sonnet v1 rubric (generators use Opus, so judge family is disjoint). With 4 parallel workers, a 30-problem × 3-battle run finishes in ~5-8 minutes.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bench.py" judge \
  --a "$1" --b "$2" \
  --battles "${3:-3}" \
  --workers 4
```

When finished:
1. Summarize the Elo table that the script prints.
2. Mention the saved `runs/battles-*.json` path so the user can re-aggregate later with `/brainstormingbench:leaderboard`.
3. If the judge emitted a `WARN` line about model-family overlap, surface it — that means the judge is the same family as one of the generators, and results may be biased.
