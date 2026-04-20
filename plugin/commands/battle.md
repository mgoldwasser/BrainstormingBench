---
description: Blinded pairwise battle between two brainstorming skills/plugins on one problem.
argument-hint: <a-slash-command> <b-slash-command> <problem-id-or-quoted-text>
---

Run a BrainstormingBench head-to-head battle between two Claude Code brainstorming skills or plugins on a single problem.

**Arguments**
- `$1` — slash command for system A, e.g. `/brainstorm-kit:brainstorm`.
- `$2` — slash command for system B, same format.
- `$3` — either a BrainstormingBench problem id from `plugin/scripts/problems/v1.json` (e.g. `product-01`, `tech-03`) **or** a literal problem in double quotes.

**What to do**

Run the battle via Bash. Do **not** brainstorm or judge yourself — the script runs each skill in its own `claude -p` subprocess and then calls the Sonnet judge with the frozen v1 rubric.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/bench.py" battle \
  --a "$1" --b "$2" \
  --problem "$3" \
  --battles 3 \
  --allow-everything
```

When the command finishes, summarize in 3-5 lines:
1. The overall winner (A = `$1`, B = `$2`, or tie) and the sub-criterion breakdown (novelty / diversity / usefulness) printed to stderr.
2. One sentence on *why* the winner won, drawn from the judge's `reasoning` field in `runs/battle-*/battle.json`.
3. If the judge warned about model-family overlap, surface that warning prominently.

Do not re-run or second-guess the judge. Do not re-brainstorm. The script output is authoritative.
