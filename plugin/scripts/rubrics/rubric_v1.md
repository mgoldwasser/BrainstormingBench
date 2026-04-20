# Judge rubric v1 (FROZEN 2026-04-14)

You are judging two anonymous brainstorming responses, **A** and **B**, to
the same problem. You must pick the response with greater **overall
creative value**.

Overall creative value has two equally-weighted halves:

- **Portfolio quality (50%)** — measured across the whole response: did
  the system explore the space well?
- **Best-idea quality (50%)** — measured on the single strongest idea in
  each response: if the user could only act on one thing from this
  response, how good is that one thing?

Each half has three equally-weighted sub-criteria, so the full rubric is
six sub-criteria weighted 1/6 each.

## Portfolio half (50%)

Scores the full response.

1. **Novelty.** Would a competent professional, asked this question cold,
   have missed these ideas? Ideas that are surprising or non-obvious score
   higher than ones that any reasonable person would have reached. Pure
   weirdness without insight does not count — the novelty should feel
   like it reveals something about the problem.

2. **Diversity.** Do the ideas span meaningfully different approaches, or
   are they variations on a single theme? A response that proposes 10
   variants of "run a marketing campaign" is low-diversity. A response
   that reaches into product design, pricing, distribution, partnerships,
   and brand identity is high-diversity. Measure the *spread* of the
   response. **A response with only one idea scores low on diversity by
   construction — that is expected and correct.** Do not penalize it
   further; the best-idea half is where single-idea responses earn their
   score.

3. **Usefulness.** Are at least some of the ideas actually actionable?
   An idea is actionable if a reasonable team could describe a concrete
   first step within a week. Universally impractical responses score low
   even if they are novel and diverse.

## Best-idea half (50%)

You pick the single strongest idea from each response, then score those
two picks head-to-head. If a response contains only one idea, that idea
is the pick by default.

**How to pick.** From each response, pick the *one* idea that you would
most want to act on as a member of the team that asked the question.
Hold the pick in mind — do not announce A's pick before reading B, to
avoid anchoring.

1. **Insight.** Does the chosen idea reveal something non-obvious about
   the problem? This is different from portfolio novelty: here we care
   about depth per idea, not breadth across ideas. An idea that reframes
   the problem or exploits a subtle dynamic scores high.

2. **Practicality.** Could a competent team describe a concrete first
   step within a week *and* a plausible path to the full outcome?
   Stricter than portfolio usefulness: it is about *this specific idea*,
   not "at least one of the ten." An idea that is insightful but needs a
   miracle to execute scores low.

3. **Differentiation.** Does the chosen idea give meaningful advantage
   over the obvious alternatives? Is it hard for a competitor to copy,
   does it exploit something specific to the situation, or does it bet
   on a non-consensus view? An idea that is merely a reasonable action
   is low on differentiation — we are looking for edge.

## Procedure

1. **Read the problem.** Form a mental picture of what a strong response
   looks like.
2. **Read response A in full, then response B in full.** Do not compare
   while reading.
3. **Pick each side's strongest idea.** Quote or paraphrase the chosen
   idea from A in `best_idea_a` and from B in `best_idea_b`.
4. **Score the portfolio half.** For novelty, diversity, and usefulness,
   note which response is stronger across the full list.
5. **Score the best-idea half.** For insight, practicality, and
   differentiation, compare only the two picks to each other.
6. **Declare the overall winner.** Weigh the two halves equally. Ties
   are allowed when the responses are genuinely close on balance; do not
   use "tie" to avoid hard calls.

## Biases to resist

- **Length bias.** Do not reward a response simply for being longer. A
  tight, strong response beats a long, repetitive one. In particular,
  do not let the portfolio half's diversity criterion override a clear
  best-idea advantage; the two halves are equal.
- **Confidence bias.** A response that sounds sure of itself is not
  necessarily better. Evaluate the ideas, not the tone.
- **Format bias.** Ignore bullet styles, numbering, markdown. Evaluate
  content only.
- **Expertise-signal bias.** Do not reward jargon or insider vocabulary
  unless it actually produces a better idea.
- **Position bias.** Which response is labeled A vs B is randomized. Do
  not let position affect your judgment.

## Required output

Return a JSON object with exactly these keys, in this order:

- `reasoning`: a brief (4–10 sentence) chain of thought explaining how
  you weighed the six sub-criteria and arrived at the overall winner.
  The reasoning field must come before the verdicts so your reasoning is
  not post-hoc.
- `best_idea_a`: a one-sentence description of the strongest idea you
  picked from response A.
- `best_idea_b`: a one-sentence description of the strongest idea you
  picked from response B.
- `novelty_winner`: `"A"`, `"B"`, or `"tie"`.
- `diversity_winner`: `"A"`, `"B"`, or `"tie"`.
- `usefulness_winner`: `"A"`, `"B"`, or `"tie"`.
- `insight_winner`: `"A"`, `"B"`, or `"tie"`.
- `practicality_winner`: `"A"`, `"B"`, or `"tie"`.
- `differentiation_winner`: `"A"`, `"B"`, or `"tie"`.
- `winner`: `"A"`, `"B"`, or `"tie"` — the overall winner.
