# The reference adapter at Gate 4

## Why

> Item 6 of #9, approved design `docs/specs/contract-shaped-tests/design.md`, step 2: "product-rebuild: the post-Gate-3 check, the adapter feature's brief, `adapter.py audit`, and Gate 4 recording the adapter hash." Step 1 (rspec verifying through `reference.run.adapter`) shipped in tammai/rspec#20.

When a rebuild's locked contract isn't the reference's API, its recorded tests are proven on the reference through an adapter. The pipeline has to know when one is needed, how to build it, how to trust it (it must not answer by itself), and that it can't change unseen once the tests are proven.

## Acceptance criteria

- **AC-001** (design 1) `sources.yaml` `reference.adapter` takes `required` or `none` (empty means none). `validate.py` refuses any other value.
- **AC-002** (design 3) `adapter.py audit` reads the adapter's latest run in its git-ignored request log (`parity/adapter/requests.jsonl`: a `{"start": …}` line each time the adapter starts, then one object per request with `method`, `path`, `status`, `reference_calls`). It fails, naming each request, on a response that no reference call backs. A 501 (operation not mapped) and a gateway 502-504 (reference down) don't count, since they can only fail a test. It also fails on a malformed line or a log with no start line. It reports `not run` (exit 2), never a pass, with no log or when nothing was answered from the reference.
- **AC-003** (design 2-3) `gate.py lock gate-4` refuses:
  - when `reference.adapter` is a value it doesn't know (never read as none);
  - with `required`:
    - while `docs/rspec.json` sets no `reference.run.adapter`;
    - while `adapter/` holds no committed file;
    - while the request log is committed;
    - while the audit doesn't pass;
    - while the audited run started before the adapter's last commit.

  It records the audit's result in the lock.
- **AC-004** (design 3) Gate 4 always protects `adapter/` (new workbenches list it from the start). It hashes only the files git tracks there, so ignored build output never enters the lock. gate-guard keeps them read-only until a reopen. A workbench without an adapter hashes nothing there.
- **AC-005** (design 1-2) `SKILL.md` and the briefs say when to set `reference.adapter` (after Gate 3, when the locked contract isn't the reference's API), and how the adapter is built: as an sdlc feature in the workbench's `adapter/`, pass-through and stateless, logging every request with its reference calls, answering 502 when the reference is down. They also say that verify runs only once the adapter is set.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | `skills/rebuild-pipeline/eval/gates_rspec.py` › adapter › validate.py refuses a reference.adapter that is not required or none | `python3 skills/rebuild-pipeline/eval/gates_rspec.py adapter` |
| AC-002 | `skills/rebuild-pipeline/eval/gates_rspec.py` › adapter › adapter.py audit is not run without a log, fails on an unbacked response | `python3 skills/rebuild-pipeline/eval/gates_rspec.py adapter` |
| AC-003 | `skills/rebuild-pipeline/eval/gates_rspec.py` › adapter › gate-4 refuses with no adapter set, then while the audit fails | `python3 skills/rebuild-pipeline/eval/gates_rspec.py adapter` |
| AC-004 | `skills/rebuild-pipeline/eval/gates_rspec.py` › adapter › gate-4 locks and hashes the adapter's source | `python3 skills/rebuild-pipeline/eval/gates_rspec.py adapter` |
| AC-005 | manual | pipeline text, checked against the design at Review |

## Must never break

- A workbench with `reference.adapter` empty or `none` locks Gate 4 exactly as before. The `level2` group stays green.
- The adapter's log holds no request or response bodies, and it stays git-ignored: it names the hidden tests' requests, and lanes hold the workbench.

## Decisions

| Decision | Chosen | Ruled out |
|---|---|---|
| Where the log lives | `parity/adapter/requests.jsonl`, outside `adapter/` | Inside `adapter/`: Gate 4 hashes that folder, so every re-verify after the lock would break the lock's integrity |
| How `adapter/` gets protected | Gate 4's `REQUIRED_PROTECTS`, so older workbenches get it at their next lock | Only when an adapter is required: the hash list would then depend on a field someone could clear after the lock |
| Who decides "required" | The user at Gate 3 (judgement: is the contract the reference's API?), recorded in `sources.yaml` | A script comparing APIs: GraphQL against REST has no mechanical answer |

## Review

**What fired:** Code, because Public Surface lists `adapter.py audit` and `sources.yaml reference.adapter`. Low risk, so it ran without asking. It ran `sdlc:code-reviewer` on opus at full depth, over three rounds; the user chose the third at the review cap. The user accepted the criteria rewritten after round 1 (trust anchor).

**Round 1: FAIL** (`.sdlc/.work/findings/2026-11-16-m-reference-adapter-gates/code-reviewer-r1.md`)
- **H1.** A 501 for an unmapped operation blocked Gate 4 for good. **Fixed:** 501-504 count as declining.
- **H2.** Ignored build output under `adapter/` was hashed. **Fixed:** only git-tracked files are hashed, and the lock refuses when git can't list them.
- **H3.** An unknown value or a missing `sources.yaml` read as "no adapter". **Fixed:** both refuse.
- **M1.** The log wasn't tied to a run or an adapter version. **Fixed:** a start line per run, compared with the adapter's last commit.
- **M2.** The committed log named the hidden tests' requests. **Fixed:** the log is git-ignored, and the lock records the audit's result instead.
- **L1.** Every new workbench said it was "scaffolded before". **Fixed:** the scaffold lists `adapter/`.
- **Also fixed:** L2, L4, L5 and F1-F3.

**Round 2: FAIL** (`code-reviewer-r2.md`)
- **R2-H1.** Only the latest run was audited, so restarts and versions before a fix escaped. **Fixed:** every run since the adapter's last commit is audited, and Gate 4 refuses while an open level-2 HTTP criterion has no passing run since that commit.
- **R2-M1.** An older workbench was told to commit the log. **Fixed:** an un-ignored log is refused first.
- **R2-M2.** A start with no timezone crashed the lock. **Fixed:** it gives one error line.
- **R2-L1.** Non-ASCII file names crashed the lock. **Fixed:** `ls-files -z`.
- **R2-L2.** Start values were printed raw. **Fixed:** escaped.
- **R2-L3.** A start line with an extra key read as a bad request. **Fixed.**
- **Also fixed:** R2-F1-F3.

**Round 3: PASS** (`code-reviewer-r3.md`). Its new items:
- **R3-L1 (bug).** An older version's malformed lines blocked the gate. **Fixed test first:** lines before this version's first run are skipped.
- **R3-L3.** With no holdout split, Gate 4 named the wrong cause. **Fixed:** it says to run `holdout.py split` first.
- **R3-L2 and R3-F1.** Documented in the brief and the CHANGELOG.

`verify.py` passes apart from the baseline's eval failures.

**Ticket**
- R3-M1: hidden criteria aren't re-checked against the adapter version, because their tests can't be re-recorded after the split. It is documented as a known gap, with the rule not to change the adapter between the split and the first Gate 4 lock. A hard check would need the holdout repo's runs, or a refusal of adapter commits after the split. The user decides.

**Drift:** recorded in Deviations: the helpers in `gate.py` and `adapter.py`, and the `lock.schema.json` key.

**Manual (AC-005):** the reviewer checked it against design points 1-3 in each round. The wording gaps it found are fixed.

**Baseline:** the test step's only failures are the four listed in `.sdlc/baseline.md`.
