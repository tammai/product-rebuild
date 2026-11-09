# GP — Production readiness → GATE 5: prod-ready lock (terminal)

Feature-complete ≠ production-ready. This gate verifies the difference BY DOING.
Run fully when the slice plan completes; run the lightweight subset (deploy + backup +
error tracking) at every slice.

**3.0.0 (05 P8): one checklist, rspec's.** The checklist is `docs/production-readiness.md`, which rspec writes
because a rebuild's goal is `production`; the items below are what GP adds to it (proposed upstream in
`docs/rspec-pr/` of this plugin), and the evidence goes after each item there. GP's own work is execution:
`python3 scripts/gp.py nfr` lists every NFR with its stated Verification in `parity/gp/nfr-evidence.md`; run each
against the **production candidate** (load tests where the NFR says; drills are the user's to perform), put the
evidence, result and who performed it in its row, and `python3 scripts/gp.py check` until it passes.
`gate.py lock gate-5` refuses, all at once, while: an item of rspec's checklist is unchecked; an NFR row is
incomplete; any slice's hidden suite has a failure or a test that did not run; an equivalence trace is red with
no departure; a high finding is open; a departure is still `proposed`; an MVP criterion is below level 1.

Two checklists follow. Use the first for a service the rebuild owns and operates; use the
client-app one below **in addition** for anything shipped to a device or an app store, and
**instead** when `architecture.target_shape` is `client-only` and there is no server in
scope. Picking the wrong one produces the classic learning-project ending: a restore drill
performed on a database nobody owns, and no rehearsal of the one release that cannot be
undone.

Checklist — each item needs EVIDENCE (log, recording, doc link), not assertion:
- Security: authn/authz reviewed against `docs/domain.md`'s permissions table; secrets
  management; dependency/container scans green; headers, rate limits, input validation tested.
- Data safety: automated backups running; restore ACTUALLY performed into a clean
  environment and verified; migration rollback exercised once.
- Observability: structured logs, error tracking, metrics + alerts; "is it up / erroring
  / slow" answerable without SSH.
- Operations: one-command deploy; rollback documented and rehearsed; upgrade path
  written; runbook for top 3 failure modes.
- Docs: install/deploy doc good enough for a stranger; architecture doc matches final
  ADR state.
- Incident dry-run: one simulated failure (kill DB / fill disk) handled using only the
  runbook. The USER performs the drills; you prepare and observe.
- **Equivalence against the reference** (posture `observe` or `own-code`, reference run locally): every trace
  recorded across all slices replays green on the **production candidate** — not on a dev
  box, not on the build that happened to be around when the slice closed — or the difference
  is a decided departure (`python3 scripts/equiv.py accept "<trace>" --reason "..." --by "<who>"` writes it to
  `docs/departures.yaml`). Run `python3 scripts/equiv.py replay --all` against the candidate and cite the
  `parity/<date>-equiv.xml` it produces.

  `gate.py lock gate-5` refuses while the newest equivalence run has a failing trace that no departure explains. A red trace says the
  rebuild returns something the old system did not, on traffic recorded from the old system
  before the rebuild existed — and Gate 5 is terminal, so nothing downstream catches it.

  Accepting a difference does not make the trace green and is not meant to. It makes it
  explained, which is exactly what this checklist asks of every other thing that is still
  imperfect. A project with three accepted differences and a sentence about each is in better
  shape than one with an equivalence suite nobody ran, and the report can tell them apart.

## The client-app checklist (`target_shape: client-only`, or any shipped client)

The list above assumes the thing being made production-ready is a service you can reach,
restore and roll back. A client app breaks three of those assumptions: **you cannot roll a
release back**, **the data at risk is on devices you cannot reach**, and **the deploy is
gated by someone else's review queue**. Run this list instead — same rule, evidence by
doing, not asserting:

- **Release mechanics, rehearsed end to end.** Signing identities and provisioning profiles
  in CI (not on a laptop), with their expiry dates recorded somewhere that will be read
  before they lapse; a store build submitted, reviewed and released to at least an internal
  track; the exact release runbook written while doing it, not after.
- **Roll-forward, because there is no rollback.** A staged/phased rollout with **halt
  criteria stated before the release goes out** (crash-free floor, error-rate ceiling); the
  kill switch and forced-upgrade path from the `release-rollout` ADR actually exercised —
  flip the flag, watch a build refuse to run, turn it back. An untested kill switch is a
  belief, and the day you need it is the day you learn which.
- **On-device data safety** — the mobile analogue of the restore drill, and the item most
  likely to be skipped. Install the **old** app, use it until it holds real state, upgrade
  **in place** to the new build, and verify: session preserved (or the designed fallback
  actually happens), local data present, unsent work not lost, files intact. Do it on a
  device restored from a real backup, on the **oldest supported OS**, and once with the
  upgrade interrupted mid-migration (force-quit) to prove the resume path. Record the
  migration telemetry the ADR specified, showing the outcome.
- **Crash and error observability.** Reporter live in the release build with **symbol/dSYM
  upload verified by reading a real symbolicated stack trace** — not by the upload step
  exiting 0. Crash-free-sessions and ANR dashboards exist, with alert thresholds set, and you
  can answer "is this version crashing, and for whom" without a debugger.
- **Offline and degraded behavior, tested.** Airplane mode, captive-portal Wi-Fi (connected
  but nothing resolves), and a slow link. Every feature behaves as its declared offline
  policy says it does; nothing hangs forever on a default timeout.
- **Security posture on the device.** Tokens in the platform keystore and nowhere else,
  verified by inspecting app storage; no PII or credentials in logs or crash breadcrumbs;
  release builds obfuscated/minified with symbols retained for reporting; certificate and
  permission posture reviewed against what the app actually needs.
- **Store and platform compliance.** Privacy manifest / data-safety declaration matching what
  the app really collects, permission usage strings, minimum OS floor matching the mined
  install base, and app size measured on the store's terms.
- **Parity of the invisible surface.** Deep links and URL schemes resolve to the same places
  the old app resolved them; push notifications still arrive to upgraded installs (token
  re-registration verified); analytics events downstream dashboards depend on still fire.
  Nobody reports a broken deep link or a flat dashboard — they just stop using the thing.
- **Docs and drills.** Release runbook good enough for someone else to ship a build;
  architecture doc matching the final ADR state; one incident dry-run using only the runbook
  — a bad release detected, halted, and remediated by roll-forward.

## Gate 5 review
Walk the evidence per item. Lock on explicit approval: `gate.py lock gate-5`.
This is the finish line — the result now matches the promise: completed, full-featured,
production-ready.
