# Production readiness

Nothing ships to production until every item is checked. Put the evidence after the item (a test, CI job, dashboard, runbook or document). An item that does not apply is checked and marked `(n/a: <reason>)`. A drill is performed, not described: name who did it and when.

## Security
- [ ] Every threat in threat-model.md is mitigated and its test passes, or listed as an accepted risk
- [ ] Authorization reviewed against the permissions table in domain.md, with a test for every role and tenant boundary
- [ ] Dependency, container and secret scanning run in CI, green
- [ ] Authentication: password policy or SSO, lockout or rate limiting on login
- [ ] Rate limits and input validation tested on every public endpoint
- [ ] Security headers, TLS everywhere, secure cookie settings

## Performance
- [ ] Load test proves every performance NFR at the expected peak, run against the production candidate
- [ ] Slow-query and payload-size budgets checked

## Requirements (NFRs)
- [ ] Every NFR in nfr.md has had its stated Verification run against the production candidate, with the evidence linked

## Reliability
- [ ] Service level objectives defined (availability, latency) with an error budget
- [ ] Automated backups running
- [ ] Restore drill performed into a clean environment, data verified after it, and timed
- [ ] A database migration rolled back once (or its tested forward fix applied once)
- [ ] Graceful degradation and retries for every external dependency

## Observability
- [ ] Structured logs without personal data or secrets
- [ ] "Is it up, erroring, slow?" answerable from dashboards, without shell access to a server
- [ ] Metrics and alerts for each SLO, routed to someone on call
- [ ] Error tracking with release tagging

## Operations
- [ ] One-command deploy
- [ ] Deploy and rollback runbook, rollback rehearsed once
- [ ] Upgrade path written (how the next version reaches production)
- [ ] Runbook for the top three failure modes
- [ ] Incident dry run: one simulated failure (database down, disk full) handled using only the runbook, performed by a person
- [ ] Database migrations are reversible or have a tested forward fix
- [ ] Incident response: who is paged, where status is posted

## Documentation
- [ ] Install and deploy guide good enough for someone who has never seen the project
- [ ] Architecture document matches the accepted ADRs as built

## Privacy and compliance
- [ ] Personal data inventory: what is stored, why, how long
- [ ] Data export and deletion for a user
- [ ] Privacy policy and terms published
- [ ] Applicable regulations reviewed (GDPR, local data laws)

## Accessibility
- [ ] WCAG 2.2 AA audit of the main flows, issues fixed

## Parity with the reference (rebuilds; delete this section otherwise)
- [ ] Every equivalence trace recorded from the reference replays green on the production candidate, or its difference is a decided departure
- [ ] Every hidden acceptance test passes on the production candidate, or its difference is a decided departure

## Client app (anything shipped to a device or an app store; delete this section otherwise)
- [ ] Release mechanics rehearsed end to end: signing identities, provisioning, store submission
- [ ] Staged or phased rollout with a halt criterion (there is no rollback on a device)
- [ ] On-device data safe across an upgrade from the previous release
- [ ] Crash and error reporting live in the release build, with symbols uploaded
- [ ] Offline and degraded network behaviour tested (airplane mode, captive portal)
- [ ] Tokens only in the platform keystore; no secrets in the bundle
- [ ] Store and platform compliance: privacy manifest or data-safety form matches what the app does
- [ ] Deep links and URL schemes resolve to the same places as before
- [ ] Release runbook good enough for someone else to ship a build

## Cutover (modernize track only; delete this section for rspec)
- [ ] Characterization tests for every MVP feature pass against the old and the new system
- [ ] Data migration rehearsed on a production-size copy; every mapping's validation passes
- [ ] Rollback rehearsed end to end
- [ ] Cutover plan reviewed; go / no-go owner named
- [ ] Old system decommission date set, backups kept until then

## Legal
- [ ] Own product name and brand; no confusion with the original product
- [ ] Third-party and OSS licences reviewed, attributions in place
