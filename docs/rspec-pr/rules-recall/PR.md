# PR to rspec: a recall test for OSS-mode discovery (product-rebuild 3.0, spec 05 D2)

**For:** the rspec worker, to add to tammai/rspec as a recall eval for discovery in OSS mode (rspec 0.11 line).
Written in product-rebuild because product-rebuild's workers do not edit rspec; the coordinator dispatches it.
Until rspec merges it, `docs/MIGRATION-3.md` row 9 blocks product-rebuild 3.0.0.

## Why

Sign-off D2 retired product-rebuild's Rule Cards (lane R): their content is now rspec's `domain.md` rules and
criteria tagged `[code]` with `repo@commit path:line`. Lane R had the one recall measure in the pipeline: a small
billing codebase written together with the list of every business rule in it, so a run could be scored on how
many it found. Every other check (rspec's audit, fact-checker, verify) measures precision: whether what the spec
says is true. None notices a change to discovery that makes it find fewer rules. D2 moves the fixture to rspec
so that measure survives.

## What is here

```
reference-src/   ~250 lines of Rails billing code, written for this fixture
gold.yaml        the answer: 31 rules, each with its locations (path, line range), kinds and test values
```

The gold set has four error-path rules (a swallowed rescue, a decline handler, a retry backoff, an
abandon-after-three), three defaults (a default argument, a `Hash#fetch` fallback, a `||` fallback), and several
rules split across two files: the classes reported as hardest to extract. `hard:` on a rule says which.
`gold.yaml`'s header still describes its 2.x scorer; the matching rule below replaces it.

## Proposed test

1. Copy `reference-src/` outside the fixture, commit it (a real commit to cite), and run rspec's discover,
   features and stories on it in OSS mode with the module explorer reading the code. **Never** let an agent see
   `gold.yaml`: one that has read the answer is copying it.
2. Score what the spec found: a gold rule is **found** when a `domain.md` rule or a criterion tagged `[code]`
   cites a `path:line` inside one of the rule's locations. **Strict** recall also needs every `values` group in
   that rule or criterion's text (one alternative per group): the gap between a rule a test can assert on and one
   that restates the route.
3. Record recall and strict recall with the rspec version and model tier, and compare with the previous run. The
   score decides nothing on its own; a change to the module explorer or story writer briefs states its
   before-and-after numbers in rspec's CHANGELOG.

The 2.x scorer is in product-rebuild's history (`skills/rebuild-pipeline/eval/rules_recall.py` before 3.0.0),
including its self-test (perfect, empty, wrong kind, off-line and file-level citations), if a port is quicker
than a rewrite.

**The gold set is complete only as far as anyone has checked.** It was written with 22 rules; the first scored
run found 9 more the source genuinely has, added before the baseline. A citation matching no gold rule whose
claim is true of the cited line means the gold set is short: add the rule and re-score. **Changing
`reference-src/` means changing `gold.yaml`'s line numbers in the same commit.**
