---
description: Blinded pairwise battle between two brainstorming skills/plugins on one problem.
argument-hint: <a-slash-command> <b-slash-command> <problem-id-or-quoted-text>
---

Run a BrainstormingBench head-to-head battle between two Claude Code brainstorming skills or plugins.

**Arguments**
- `$1` — slash command for system A, e.g. `/brainstorm-kit:brainstorm` or `/my-plugin:ideas`. The `{problem}` placeholder is added automatically if not present.
- `$2` — slash command for system B, same format as A.
- `$3` — either a BrainstormingBench problem id from `problems/v1.yaml` (e.g. `product-01`, `tech-03`) **or** a literal problem in double quotes.

**What to do**

Run the battle via the Bash tool. Do **not** attempt to brainstorm yourself — the CLI will invoke each skill in its own `claude -p` subprocess and then call the Sonnet judge.

```bash
bench battle --a "$1" --b "$2" --problem "$3" --battles 3
```

When the command finishes, summarize in 3–5 lines:
1. The overall winner (A = `$1`, B = `$2`, or tie) and the sub-criterion breakdown (novelty / diversity / usefulness).
2. One sentence on *why* the winner won, drawn from the judge's reasoning in `runs/battle-*/battle.json`.
3. If the judge warned about model-family overlap, surface that warning prominently.

Do not re-run or second-guess the judge. Do not re-brainstorm. The CLI output is authoritative.
