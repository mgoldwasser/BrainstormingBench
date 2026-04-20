---
description: Compute absolute creativity metrics (fluency, flexibility, originality, elaboration) over a saved run. Researcher-only — requires pip install.
argument-hint: <run-dir> [<baseline-run-dir>]
---

Compute BrainstormingBench's four absolute metrics over one run directory. **These are diagnostic**; the headline output is the Elo leaderboard from `/brainstormingbench:judge`.

**Not bundled in the plugin.** Metrics depend on `sentence-transformers` and `numpy`, which are too heavy to ship in a zero-install plugin. To use this command the user must clone and install the research path:

```bash
git clone https://github.com/mgoldwasser/BrainstormingBench.git
cd BrainstormingBench
pip install -e ".[dev]"
```

After that `bench metrics` is on PATH.

**Arguments**
- `$1` — path to the run directory to score (e.g. `runs/my-skill-2026...`)
- `$2` — *(optional)* a baseline run (typically a plain-claude run) used to build the "obvious ideas" corpus for corpus-relative originality. Omit if you only care about within-response originality.

**What to do**

First check that `bench` is on PATH. If not, tell the user to run the `pip install` block above and stop — do not attempt to approximate these metrics yourself.

```bash
if ! command -v bench >/dev/null 2>&1; then
  echo "bench CLI not found — install the researcher path (see the command docs)."
  exit 1
fi
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
