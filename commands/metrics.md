---
description: Compute absolute creativity metrics (fluency, flexibility, originality, elaboration) over a saved run.
argument-hint: <run-dir> [<baseline-run-dir>]
---

Compute BrainstormingBench's four absolute metrics over one run directory. These are diagnostic; the headline benchmark output is the Elo leaderboard from `/brainstormingbench:judge`.

**Arguments**
- `$1` — path to the run directory to score (e.g. `runs/my-skill-2026...`)
- `$2` — *(optional)* a baseline run (typically a `plain_claude` run) used to build the "obvious ideas" corpus for corpus-relative originality. Omit if you only care about within-response originality.

**What to do**

```bash
if [ -n "$2" ]; then
  bench metrics "$1" --baseline "$2"
else
  bench metrics "$1"
fi
```

When done:
1. Summarize the aggregate row (mean fluency / flexibility / originality / elaboration).
2. Call out any problems where the skill scored notably low (e.g. fluency < 3, meaning fewer than three distinct ideas survived dedup).
3. Remind the user these are diagnostic numbers — the Elo leaderboard is the primary comparison signal.
