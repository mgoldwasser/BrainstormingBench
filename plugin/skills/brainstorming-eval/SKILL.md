---
name: brainstorming-eval
description: Load when the user wants to evaluate, compare, or benchmark brainstorming systems — including comparing Claude Code brainstorming plugins/skills, interpreting BrainstormingBench results, judging the creativity of AI-generated idea lists, or building on the Elo leaderboard. Do not load for generic brainstorming requests where the user just wants ideas.
---

# BrainstormingBench: session-level mental model

You are in a session where the user is evaluating or comparing brainstorming systems. This skill loads the benchmark's conceptual frame so you don't have to re-derive it from scratch each conversation.

## Headline design decisions

1. **Pairwise > absolute.** The primary output is the **Elo leaderboard** from blinded pairwise LLM-judge battles. Absolute metrics (fluency, flexibility, originality, elaboration) are diagnostic — never lead with them.
2. **Blind judging.** The judge never sees system names. Responses are labelled A and B with randomized order per battle, then position-normalized before aggregation.
3. **Judge ≠ generator family.** Generators use `claude-opus-4-6`, judge uses `claude-sonnet-4-6`. If this invariant is violated, `PairwiseJudge.check_family_disjoint` warns — surface that warning to the user.
4. **Frozen artifacts.** `problems/v1.yaml` and `judge/rubric_v1.md` are immutable. Changes go in `v2`, never in-place.
5. **Tool-agnostic.** The benchmark never imports any brainstorming tool. Adapters talk to their systems externally (slash command via `claude -p`, or replicated prompt via the SDK).

## Which command to suggest when

| User intent                                                    | Command / workflow                                                                  |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| "Which of these two is better on one problem?"                 | `/brainstormingbench:battle <a> <b> <problem>` — cheap (~\$0.50), fast (~1 min)     |
| "Where does my plugin rank against everything else?"           | `/brainstormingbench:run <cmd>` → `:judge` vs each existing run → `:leaderboard`    |
| "What are the absolute strengths/weaknesses of this system?"   | `/brainstormingbench:metrics <run-dir> [baseline]` — diagnostic numbers             |
| "Compare N systems at once, fast."                             | Spawn N `brainstorm-runner` subagents in parallel via the Agent tool, then `bench judge` |

## Parallel multi-system evaluation via subagents

The `brainstorm-runner` subagent is the unit of parallelism. To compare 4 systems on one problem without waiting 4× serial:

1. In the main session, call the Agent tool 4 times in a single message — one per system — each spawning `brainstorm-runner` with its own `(skill, problem, out_dir)` triple.
2. When all return, you have 4 response JSONs on disk.
3. Run `bench judge` across the directories pairwise (or `bench battle` for individual head-to-heads).
4. Surface the verdict and, if the user wants, update `leaderboard.md` with `bench report`.

Do not spawn `brainstorm-runner` for the judging step — judges go through `bench judge` / `bench battle`, which use the structured Sonnet judge with rubric v1.

## What not to do

- Do not have Claude brainstorm or judge *itself* when evaluating systems. The whole point is that generators are black boxes to the benchmark; if the main session starts producing ideas, that's contamination.
- Do not edit `problems/v1.yaml` or `judge/rubric_v1.md` to make a new system look better. Add `v2` files instead.
- Do not infer a winner from absolute metrics alone. Elo from pairwise battles is the comparison signal; metrics are per-response diagnostics.
- Do not suggest installing brainstorm-kit or any other tool from the benchmark code path. Adapters shell out; the benchmark never imports a tool.

## Where to read next

- `README.md` for user-facing overview
- `CLAUDE.md` for cross-file invariants (frozen files, model-family rules, position-normalization)
- `problems/v1.yaml` to see the actual problem set
- `judge/rubric_v1.md` to see what the judge is asked to evaluate
