---
description: Regenerate and show the current BrainstormingBench Elo leaderboard.
---

Regenerate `leaderboard.md` from every `runs/battles-*.json` file on disk and show the resulting table.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bench.py" report
```

Then:
1. Paste the markdown table from `leaderboard.md` back to the user.
2. Note the total number of battle records the leaderboard was built from (printed in the header of `leaderboard.md`).
3. If the leaderboard has fewer than three systems or fewer than ~30 battles per system, point out that confidence intervals will be wide.
