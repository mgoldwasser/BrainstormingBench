# Problems

This directory holds versioned, **frozen** problem sets used to evaluate
brainstorming systems.

## Freezing rule

Once a `vN.yaml` file has been released, it must not be edited. Fixing typos,
re-wording for clarity, adding or removing problems — all of these break
comparability across runs. Instead:

1. Copy `vN.yaml` to `v{N+1}.yaml`.
2. Make the changes there.
3. Update `frozen_at`.
4. Announce the new version in `README.md` at the repo root.

Old run directories pin the problem-set version they used, so historical
results remain interpretable.

## File format

```yaml
version: 1
frozen_at: YYYY-MM-DD
problems:
  - id: <category>-<NN>
    category: product | social | tech | creative | civic
    horizon: short | medium | long
    domain_knowledge: helps | neutral | unhelpful
    prompt: "<the brainstorming prompt shown verbatim to every adapter>"
```

- `id` must be unique within the set and stable across versions. If you drop
  a problem in `v2`, do not reuse its id.
- `prompt` is the exact string passed to every adapter. No preamble is added
  by the harness — adapters are responsible for their own system prompts.

## Selection criteria

A good problem for this benchmark:

- Has no obvious single right answer. If an LLM can one-shot it, it does not
  discriminate between brainstorming systems.
- Is realistic — something an actual person might ask a thinking partner.
- Has room for both near-term and far-future answers.
- Does not require current events or niche expertise that would be unfair to
  general-purpose systems.

A v1-set-wide constraint: at least 3 problems where domain knowledge helps
(so research-augmented techniques can shine) and at least 3 where domain
knowledge is unhelpful (pure-imagination work). See `v1.yaml` for the
tagging.
