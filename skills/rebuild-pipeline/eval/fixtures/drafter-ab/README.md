# drafter-ab — does the ADR drafter need the architect tier?

The audit behind 1.2.0 suggested running `adr-drafter` on Sonnet for the concerns whose playbook default
simply applies, because 7 of 11 web concerns and 20 of 21 Flutter ones do, and each draft is an
opus-at-high-effort dispatch. `spec-writer` had moved to Sonnet on a three-run comparison; the drafter had
no comparison. This is that comparison.

Each run is one drafter writing one ADR, from `playbook.py excerpt` and `dossier.md`, a fictional reference
product (Fleetwise) whose facts were written to make two concerns' defaults wrong and two right:

| Concern | The facts | What a good ADR does |
|---|---|---|
| `authn-authz` | 140 enterprise tenants need SAML/OIDC SSO and SCIM | keeps what applies, adds the federation path, names a mechanism and its cost |
| `events-queues` | 8,000 telemetry messages/s, per-vehicle order, loss under 0.1% | splits telemetry from business events, keeps outbox/inbox/DLQ for the latter |
| `storage` | nothing that conflicts | adopts §8, says how legacy ids are handled, says what it leaves alone |
| `observability` | request id lost at the Celery boundary, no readiness probe, Datadog | keeps §10, maps it to Datadog, closes both gaps |

`truth.json` holds each concern's checklist (three items, decided YES/NO by a blind judge that sees four
anonymised ADRs per concern and is not told the model) and the decision labels it allows. `tools/check.py`
is the objective half; `tools/prepare.py` builds a run directory and brief.

## Result (2026-10-26; 4 concerns × Sonnet and Opus × 2 runs; same effort, not pinned to `high`)

| | Sonnet | Opus |
|---|---|---|
| Checklist items met | 23/24 | 23/24 |
| Blind quality score (1-5), mean | 3.88 | **4.88** |
| Mean tokens per draft | 58.7K | 64.1K (+9%) |
| Mean agent time per draft | 94 s | 153 s (+63%) |

Opus scored at least as high as Sonnet in 8 of 8 pairs, and in all four concerns. The checklist did not
separate them. The judges' notes name the difference: Opus drafts more often closed a failure the others left
open (a crash between publish and mark-sent in the outbox relay, a rollup before a partition drop, keeping the
SAML entity id so tenants need not reconfigure). Unlike the spec-writer comparison, there is a consistent gap.
**Decision: `adr-drafter` stays on the architect tier.**

Also found, and fixed in this release: 4 of 8 Opus drafts wrote their header as a bulleted list
(`- concern: observability`), and no Sonnet draft did. The line-start pattern in `playbook.read_adrs` read
those as ADRs with no concern, and `gate.py lock gate-3` would have refused. The reader now accepts
bulleted and bold headers, and the agent file says to write bare lines.

## What it does not show

- The judge was a Sonnet, and `quality` is one number from one reader. A self-preference would favour Sonnet,
  and Opus won anyway; it is still one judge.
- Two runs per cell and one playbook. A one-point gap on 1-5 scales is a signal, not a proof.
- The decision-label check is not used. `authn-authz` kept the default and added SSO as `silent-default` in all
  four drafts, which is a defensible reading of the playbook's own labels, so the label is not a fair test of
  that concern; and `storage` drafts that exempted only the telemetry table were marked wrong by it, though
  the facts arguably force that exemption. The checklist tests what the ADR does instead.
- Effort was not pinned to `high` (the agent file's setting) because the agents were dispatched as
  general-purpose. Both models ran at the same default.
- No arm read the whole playbook, so this does not measure what the excerpt saves, only that drafters
  working from it produced complete ADRs. At least 13 of the 16 ADRs say they opened the
  vendored file by line range for a section the excerpt lacks, usually §4, §7, §8 or §9.5, which the sections
  they were given refer to. So the excerpt is a starting point, not a complete input.
