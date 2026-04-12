# Future work

Ideas considered and deliberately deferred from v1. Pull requests welcome.

## More / better metrics

- **Usefulness probe.** Ask a separate LLM, per idea, "could a competent
  team describe a concrete first step within a week?" and report the
  fraction of yes answers. Rubric would have to be carefully worded to
  avoid rewarding jargon.
- **Surprise-to-human proxy.** Train (or prompt) a small classifier to
  predict whether an idea *sounds like a typical Claude output* and invert
  it. This is closer to the construct "would a human have been surprised?"
  than corpus-relative originality is.
- **Idea-level rather than response-level metrics.** Judge individual ideas
  pairwise, then aggregate to response level via something other than
  majority-vote (Bradley–Terry, for instance). More expensive but more
  informative.

## Judging

- **Human-in-the-loop verification.** Sample 5–10% of battles for human
  review, use the agreement rate as a trust score on the LLM judge. When
  agreement drops below a threshold, flag the rubric as drifting.
- **Multi-judge ensemble.** Run Sonnet, Opus (when generator was Sonnet),
  and a non-Anthropic model; take majority vote. Expensive but reduces
  single-model bias.
- **Length-controlled responses.** Truncate both responses to the same
  token budget *before* judging so length bias is structurally impossible
  rather than merely discouraged.

## Problems / coverage

- **v2 seed set** covering more domains: scientific research directions,
  policy design, interpersonal advice, comedic writing. Tag each by
  whether deep expertise is expected to help.
- **Multi-turn brainstorming.** The current API is one-shot. Some systems
  really shine in dialogue; measuring that would require a harness that
  supports follow-up exchanges.
- **Structured outputs.** Some problems (e.g. product specs) benefit from
  a structured-output format rather than a flat idea list. A problem's
  schema could be declared alongside its prompt.

## Engineering / ergonomics

- **Cached embeddings.** Right now every metric run re-embeds every idea.
  Cache to disk keyed by (text, model) so repeated runs are free.
- **Cost dashboard.** Aggregate meta.cost_usd / meta.token_counts across
  `runs/` and print a per-adapter cost summary.
- **Leaderboard visualization.** Heatmap of per-problem win rates, plus a
  category × adapter table. Markdown-only for now.
- **Concurrency.** `bench run` and `bench judge` are serial. A simple async
  fan-out per problem would cut wall-time without changing any math.

## Scope deliberately *not* expanded

- **Web UI.** Out of scope; CLI only.
- **Inventing novel creativity metrics.** Stuck to the four from creativity
  psychology. Any "metric we just made up" goes here.
- **Importing brainstorm-kit internals.** Adapter talks to it externally.
  This is a design decision, not a TODO.
