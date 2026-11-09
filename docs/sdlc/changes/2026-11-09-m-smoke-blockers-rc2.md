# 3.0.0-rc.2: the smoke run's release blockers

## Why

**Request (verbatim):** "The pre-release smoke run (C:/Users/Admin/orca/e2e/smoke/REPORT.md and FINDINGS.md, read the rows named below) found release blockers in this repo. The user decided (2026-11-09): fix them now, test-first, prove each with one test reproducing the smoke finding (no second smoke run). Through sdlc as one M change." Items 1–7 of the coordinator's brief: S-38, S-54, S-55, S-57, S-16, S-37 (this repo's half), S-42 (known issue, docs only); then bump to 3.0.0-rc.2.

The smoke run drove a whole rebuild through 3.0.0-rc.1 and found six places where a script either leaks a secret, reports green on the wrong target, burns a budget on nothing, or reports a problem that is not there. Each is a release blocker for 3.0.0. They are fixed here, each proven by one eval that reproduces the smoke finding; S-42 is a spec question with no fix yet, so it ships as a stated known issue.

**The user's words:** "fix them now, test-first, prove each with one test reproducing the smoke finding (no second smoke run)." At the approval the coordinator added: "when sources.yaml reference.run.base_url is empty but reference.run is local, do not silently skip: G6 prints the open-suite target URL in its report so a human can see which build it hit (no refusal needed)."

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| S-38: a trace stores `account: <NAME>` (contracts v1's field) in place of a credential header; replay rebuilds the header from `ACCEPT_ACCOUNT_<NAME>` | a `<redacted>` header value | a named account is what replay needs to re-insert the live value; the field matches contracts' HTTP replay |
| S-38: credential = `Authorization`, `Proxy-Authorization`, `Cookie`, or any header whose name an `ACCEPT_ACCOUNT_<NAME>` line uses (a proxy or BFF account header) | a fixed list only | no plugin names a proxy header (searched rspec, sdlc); matching the account lines covers whatever header a stack uses |
| S-38: a credential header no account variable holds, or a response that contains an account's credential, refuses that trace and writes nothing | writing it scrubbed | an unnamed credential cannot be re-inserted at replay, and scrubbing a response body would make replay compare against bytes the rebuild never sends |
| S-38: a request file may name `account: <NAME>` itself | requiring the literal header | keeps the token out of the committed `.request.yaml` too |
| S-54: the refusal lives in `holdout.py` (`reference_target`) and is called by `boundary.py` (before step 0) and `holdout.py run` | a check in contracts.py | rspec verify runs contracts.py against the reference on purpose |
| S-54: the reference's address is `sources.yaml` `reference.run.base_url`, read with yamlio; compared on scheme, host (every spelling of this machine is one host) and port, the path ignored; an unreadable sources.yaml or an address that does not parse refuses; an empty value checks nothing | refusing when it is empty; a line parser (review round 1: it passed every layout it missed) | `rebuild_init.py` writes it empty, and an unknown reference cannot be matched |
| S-55: the same routable finding ids open round N+1 only when round N's attempt is recorded: `lane_plan.py archive` of a round-N fix lane, or `route.py <Sn> --attempted "<what was fixed>"` for a workbench-side fix (the user's decision after review round 2) | inferring a fix from code-repo commits and the lock/departures hashes (built first; review found it counted a new fix-lane branch as a fix and could not see a harness fix, twice) | a fix that did not work legitimately needs round 2 with the same ids, and only a record says a round was tried |
| S-57: archive writes `change.md` and `state.md` | the source basename | sdlc 3.x names both files `<feature>.md`, so the state copy overwrote the change copy |
| S-16: `--help`/`-h` anywhere prints usage and exits 0; a flag a command does not take prints usage and exits 1; nothing is written in either case | ignoring unknown flags | a typo such as `--thresold` silently engaged with the default |
| S-37: `validate.py` reads `plan/holdout.json` and fails, naming `holdout.py reconcile`, when a hidden criterion has no `visibility: hidden` entry in the manifest; an unreadable record or manifest fails too | calling `reconcile()` from validate | validate is read-only; reconcile writes, and needs the holdout folder CI does not have |
| Build runs inline in this session, one part | parts or subagents | seven small, separate fixes; the brief says no subagents |

**Bug:** each smoke row is reproduced by its AC's eval, recorded failing before the fix (`verify.py red`). Root causes: S-38 `equiv.py record` writes `request` from the request file verbatim; S-54 `boundary.py` and `holdout.py run` take `ACCEPT_BASE_URL` with no check of what it points at, and rspec verify sets it to the reference; S-55 `route.py` opens round N+1 on every run with anything routable; S-57 `lane_plan.py _archive` copies both files to `dest_dir/basename(src)`, and both basenames are `<feature>.md`; S-16 `autopilot.py main` dispatches on `args[0]` and no handler reads `--help`; S-37 nothing outside gate-4's lock compares the manifest with the split record.

**Proposals not asked for:** None.

## Acceptance criteria

- **AC-001** (S-38) Given a request file with `Authorization: Bearer <token>` and `ACCEPT_ACCOUNT_MEMBER` holding that header, when `equiv.py record` runs against a legacy server that requires it, then the trace contains no byte of the token and names `account: MEMBER`; and `equiv.py replay` with the variable set re-inserts the header and the trace is green.
- **AC-002** (S-38) Given a credential header that no `ACCEPT_ACCOUNT_<NAME>` holds, or a response that contains an account's credential, when `equiv.py record` runs, then it refuses that trace with the reason and writes no trace file.
- **AC-003** (S-54) Given `ACCEPT_BASE_URL` equal to `sources.yaml` `reference.run.base_url` (after normalising), when `boundary.py <Sn>` or `holdout.py run <Sn>` runs, then it refuses, says the URL is the reference's and to point it at the slice build, and sends no request; with `ACCEPT_BASE_URL` elsewhere, the boundary runs and its open suite prints the URL it targets (so a human sees which build it hit, also when the reference's address is empty).
- **AC-004** (S-55) Given a fix round N, when `route.py <Sn>` runs again with the same open findings and no attempt at round N recorded (a commit in a code repo is not one), then no round N+1 is written and it says round N is still open; once `route.py <Sn> --attempted "<what>"` or an archived round-N fix lane records the attempt, the same findings open round N+1.
- **AC-005** (S-57) Given two shipped lanes whose criteria were never edited, when both are archived, then the slice review reports no rewritten criteria for either.
- **AC-006** (S-16) Given a workbench where `engage` would succeed, when `autopilot.py engage --help` or `autopilot.py engage --thresold 50` runs, then it prints usage (exit 0 for help, 1 for the unknown flag) and writes no `plan/autopilot.yaml` and no commit.
- **AC-007** (S-37) Given a split whose hidden entry is missing from `docs/acceptance/manifest.json`, when `validate.py` runs, then it fails naming the criterion and `python3 scripts/holdout.py reconcile`; with the entry present, that check passes.
- **AC-008** (S-37, recurring defect "a check that passes before reading its input") Given an unreadable `plan/holdout.json`, when `validate.py` runs, then it fails saying so.
- **AC-009** (S-42) README and CHANGELOG known issues state that in a BFF/proxy stack the recorded HTTP criteria must run against the public surface the user reaches (the BFF or web server), not a lane's stub of the API, and that no plugin enforces it yet; `agents/lane-worker.md` carries the same one-line rule.
- **AC-010** The plugin version is 3.0.0-rc.2 in every manifest, with a CHANGELOG entry for these fixes.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | skills/rebuild-pipeline/eval/g6_eval.py › equiv (a signed-in trace holds no token and replays green) | `python3 skills/rebuild-pipeline/eval/g6_eval.py equiv` |
| AC-002 | skills/rebuild-pipeline/eval/g6_eval.py › equiv (an unnamed credential, or one echoed in the response, writes no trace) | `python3 skills/rebuild-pipeline/eval/g6_eval.py equiv` |
| AC-003 | skills/rebuild-pipeline/eval/g6_eval.py › reference (G6 refuses the reference's URL and sends nothing) | `python3 skills/rebuild-pipeline/eval/g6_eval.py reference` |
| AC-004 | skills/rebuild-pipeline/eval/g6_eval.py › route (a re-run with no recorded attempt opens no round) | `python3 skills/rebuild-pipeline/eval/g6_eval.py route` |
| AC-005 | skills/rebuild-pipeline/eval/lanes_rspec.py › archive2 (two untouched lanes archived, no rewrite reported) | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py archive2` |
| AC-006 | skills/rebuild-pipeline/eval/gp_eval.py › help (engage --help and an unknown flag change nothing) | `python3 skills/rebuild-pipeline/eval/gp_eval.py help` |
| AC-007 | skills/rebuild-pipeline/eval/holdout_eval.py › validate (a dropped hidden entry fails validate, naming reconcile) | `python3 skills/rebuild-pipeline/eval/holdout_eval.py validate` |
| AC-008 | skills/rebuild-pipeline/eval/holdout_eval.py › validate (an unreadable split record fails validate) | `python3 skills/rebuild-pipeline/eval/holdout_eval.py validate` |
| AC-009 | manual | docs text; the user's testing rule rules out grep tests of docs. Checked in Review against the three files. |
| AC-010 | manual | a version string; the user's testing rule rules out manifest-field tests. Checked in Review with a grep for `3.0.0-rc` across manifests. |

## Must never break

- A trace recorded without credentials stays byte-identical to what `equiv.py` wrote before (traces are committed evidence; a re-format diffs every file).
- rspec verify can still run recorded tests against the reference: nothing outside G6 refuses the reference's URL.
- A fix round whose fix did not work can still be followed by the next round, up to the cap.
- `validate.py` never writes: it reports the dropped entry, `holdout.py reconcile` restores it.
- Every documented `autopilot.py` invocation (SKILL.md, references, commands) keeps working.

## Failure modes

- Untrusted or secret input written to git (a credential in a request or response) → AC-001, AC-002.
- A check that passes before reading its input (recurring defect, High) → AC-008; S-54's check reads `sources.yaml` and checks nothing only when the reference address is empty (Decisions).
- Persisted data: lane archives written by rc.1 hold the state file under the change file's name; they are not migrated (Out of scope).
- Concurrency, scale, crash mid-write: none apply beyond what the scripts already handle.

## Out of scope

- S-42's fix (which surface HTTP criteria bind to in a BFF stack): a spec question for rspec and sdlc; here only the known issue and the lane-worker rule.
- rspec's half of S-37 (`verify_report.py` keeping entries it cannot see): rspec's own fix.
- Re-writing rc.1 lane archives already on disk; re-archiving a lane is refused by design, and the smoke workbench is the only one.
- A second smoke run (the user's decision).

## Review

- **Recommended and chosen:** security and code. Security fired on `Risk: high` (a token committed in traces, S-38) and on untrusted request files and responses; code fired on `Risk: high` and a Public Surface. The coordinator approved the plan naming both (msg_77cf5e2b11ac).
- **Verdicts:**
  - Round 1: security FAIL (SEC-1..4 high, SEC-6/8/9 bugs) → `.sdlc/.work/findings/2026-11-09-m-smoke-blockers-rc2/security-r1.md`; code FAIL (CR-2, CR-3, CR-4, CR-8, CR-9 high, plus bugs) → `code-reviewer-r1.md`.
  - Round 2: security FAIL (SEC-10 high) → `security-r2.md`; code FAIL (R2-1, R2-2, R2-5, R2-6 high) → `code-reviewer-r2.md`. Past the cap, the user chose one more round: fix the security highs, fail closed on the reference address, and record fix attempts rather than infer them (msg_efdb9c008ece).
  - Round 3: security PASS → `security-r3.md`; code FAIL (R3-1 high) → `code-reviewer-r3.md`. The user chose to fix R3-1 with no fourth review (msg_5599a8f3b6fc; Deviations: `waived round 3`).
- **Fixed:**
  - S-38, the credential scan. Every account's credential is scanned in every decoded string of a trace (SEC-1, SEC-2, CR-9). A credential the scan cannot read refuses the recording (R2-2). Cookie names and short cookie pieces are not treated as secret (SEC-6, R2-4). Replay output is scrubbed (SEC-5).
  - S-38, where a signed request can go. Its path must be relative, and `do_request` checks the host urllib will actually dial (SEC-3, SEC-10). Traces written before rc.2 that hold a credential get a warning (CR-10). Tests: `g6_eval.py equiv`.
  - S-54. The reference check reads `sources.yaml` with yamlio and fails closed (SEC-4, R2-5). It compares only the server, ignoring the path (CR-2). Equivalence replay also refuses the legacy or reference URL, and the boundary stops on that refusal (CR-8, R2-1). A lane that applies but is not set up is reported not run, and G6 goes on (R3-1). Tests: `g6_eval.py reference` and `g6_eval.py equiv`.
  - S-55. A fix is no longer inferred from commits and hashes (CR-3, CR-4, CR-5, R2-6). A round counts as attempted only when an archived fix lane or `route.py <Sn> --attempted` records it. Test: `g6_eval.py route`.
  - S-37. `validate.py` names a hidden criterion that is open again (CR-7) and fails on a record of the wrong shape (SEC-9). Test: `holdout_eval.py validate`.
  - S-16. `-h` given as a flag's value is the value, not a help request (CR-14). Autopilot runs under `-OO` (CR-15), and `--help` works outside a workbench (R2-14). Test: `gp_eval.py help`.
  - One existing check, `gp_eval.py` budgets "route.py's round cap", relied on the duplicate-round bug; it now routes a new finding for its second run.
- **Tickets:** R3-2, R3-3, R3-5..R3-11, security-r3 L-2..L-4, SEC-7/R2-15, R2-3/R2-16, CR-1/R2-8, CR-6, CR-13 and R2-17 are in `docs/sdlc/todo.md`. The remaining low and design notes (CR-11/12/16..20, R2-9..13, R2-18) are fixed or superseded by the fixes above.
- **Drift and manual checks:**
  - Deviations in the state file:
    - new helpers `reference_target`/`same_server` (holdout.py) and `attempted` (route.py, replacing `fix_evidence`);
    - AC-004 and the S-54/S-55 Decisions rows rewritten to the built design;
    - the round-3 waiver;
    - local commit only.
  - AC-009 was checked by reading. README "Known issues", CHANGELOG "Known issues" and `agents/lane-worker.md` "Test cadence" each carry the BFF/public-surface rule and say no plugin enforces it.
  - AC-010 was checked by reading: `.claude-plugin/plugin.json` is `3.0.0-rc.2`, and the CHANGELOG says so. `marketplace.json` carries no version.
  - Full test command: only the 4 failures listed in `.sdlc/baseline.md` (lane_guards worktree, run_supervision dead driver ×2, windows_and_upgrade CRLF lock).
- **Security:**
  - Findings as above.
  - Dependency audit: not run. Stdlib only, plus vendored PyYAML under `_vendor/`, which `pip-audit` does not read.
  - No secrets in the diff: the eval tokens are fixtures.
- **Lessons filed:** none.
