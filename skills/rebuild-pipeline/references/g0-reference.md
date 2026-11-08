# G0 — Reference selection + license posture

Goal: pick the reference and record the legal posture BEFORE any agent reads anything.

## Onboarding interview (ask, don't assume)
1. Which reference product, or which category? If category only, propose 2–3 concrete
   OSS candidates and compare: domain fit, codebase readability for the user's stack
   familiarity, upstream activity (parity loop needs a living reference), deployability.

   **A reference the user already owns is a first-class case**, not a degenerate one:
   "rebuild our own legacy app on a new stack" is the same pipeline with three fields
   different. Record `reference.kind: own-code` and `reference.upstream: frozen` (a legacy
   app that is being replaced has stopped shipping), and note what that turns off — G6's
   upstream re-mine has nothing to track, and question 2 stops being about someone else's
   licence. Everything else gets *easier*, not weaker: reading the code is unrestricted, the running
   instance is the app the user already has, and the old app is a permanent arbiter for
   ambiguous behavior rather than a moving target. Ask whether the *replacement* is meant to
   be distributed differently from the original (open-sourced, sold, handed to a client);
   that is still a posture decision, just about their code rather than a third party's.
2. Distribution intent — this is the license-posture decision:
   - Private/learning use → reading any OSS source (incl. GPL/AGPL) as reference is
     low-risk; the spec side may read the code (posture `observe`).
   - Possible closed-source distribution later → treat copyleft references clean-room:
     specify behavior from the running product, docs and API only (posture `strict`).
   - Permissive reference (MIT/Apache/BSD) → no restriction; vendoring allowed with attribution.
   Record the answer in `license-posture.md`. State clearly you are not a lawyer; if
   distribution plans are ambiguous, recommend professional advice before locking G0.

   **Then the posture, `sources.yaml` `reference.posture`** (05 P3). Show the licence and ask;
   the legal fit is the user's call, never yours:
   - `strict`: the spec side only observes and records behaviour; nobody reads the code.
   - `observe` (the default for a third-party reference): the spec side may also read the code
     (rspec OSS mode); build lanes never do.
   - `own-code` (the default for `kind: own-code`): build lanes may read the reference too.

   Under every posture, build lanes never read the hidden tests. `hooks/scripts/reference_guard.py`
   enforces both for lanes; it is a guard, not a sandbox. `validate.py` fails on any other value
   and warns on `own-code` for a reference the user does not own.
3. Optional secondary reference for UX comparison only.

   **Ask 3, 5 and 6 together, each with its usual answer**, and take any the kickoff already gives:
   for a permissive third-party reference that is "none", "no, first attempt" and "nothing", and
   one message settles all three instead of a stop each.
4. **What is being rebuilt, and against which architecture playbook.** Two fields, one
   question, both written to `sources.yaml`'s `architecture:` block and both read later — ask
   them here because the stack decision is weeks away and the answers change rspec's tech
   stage, G5 and GP:
   - `target_shape`: `fullstack` (the rebuild owns backend and frontend) or `client-only`
     (the API already exists and stays put; the rebuild is one client against it). Ask it
     plainly — "does this rebuild include the backend, or does it talk to an API that
     already exists and isn't changing?" — because the answer flips the contract from
     *drafted* to *transcribed* (rspec's modernize track), and a project that discovers this
     at Gate 4 has specified the wrong product.
   - `playbook`: which entry in the plugin's `references/playbooks/` supplies the stack (its
     stack line becomes rspec's stack preference) and the scaffold manifest the code repos
     are created from. Offer what is there (`web-modular-monolith`, the org default for
     `fullstack`; `mobile-flutter` for a Flutter client), a workbench-local path if the user
     has written their own, or `none` to make every stack decision blank-slate. Read the
     candidate's `not-applicable-when:` frontmatter aloud before recording it — discovering
     at Gate 3 that no playbook fits is the expensive way to learn it.

   A user rebuilding their own React Native app in Flutter answers: `kind: own-code`,
   `upstream: frozen`, `target_shape: client-only`, `playbook: mobile-flutter`.
5. **Has this rebuild been tried before?** By whom, how far it got, why it stopped, and
   what survives — a branch, a half-done schema, a doc, an ADR someone wrote and lost the
   argument about. Ask it now because a failed prior attempt is the cheapest possible
   source of ground truth about where this one will get hard, and because the parts that
   survive are either inputs or traps, and only the user can say which. "No, first attempt"
   is a complete answer; write it down so the question is not re-asked at Gate 3. Record under
   `## Prior attempts` in `license-posture.md`.
6. **What may agents not touch or read?** Paths inside the reference, adjacent repos,
   production systems, customer data, anything under legal hold. For an `own-code`
   reference this is the question that does the most work — the user's own monorepo has
   corners that are somebody else's, and agents have no way to know. Record under
   `## Off-limits` in `license-posture.md`, and then **put every path and URL from the
   answer into `sources.yaml`'s `denied:` list**: the prose is for the human, the deny list
   is the thing agents actually read, and an off-limits path recorded only in prose is
   an instruction that exists nowhere an agent will see it.

## Actions
- Scaffold: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/rebuild-pipeline/scripts/rebuild_init.py <name>`
- Fill `sources.yaml`: exactly what agents may fetch/clone, derived from the posture.
  If clean-room: the reference repo goes on the deny list.
- **Give the workbench a remote now, before rspec's discovery starts.** Everything the pipeline
  is about to produce — the feature list, ADRs, gate history — is unreproducible: re-running
  discovery yields different findings, not the decisions you argued yourself into. Waiting
  until "there's something worth backing up" means the loss window covers the spec stages,
  the phases with the most output.
  ```sh
  gh repo create <name>-workbench --private --source . --push
  # Durability-only remote? Turn the host's CI off so pushes stay silent:
  gh api -X PUT repos/<owner>/<name>-workbench/actions/permissions -F enabled=false
  ```
  Pushing stays manual and stays your job: `python3 scripts/pause_check.py` flags anything that has not
  left the machine before a session ends, but nothing pushes on your behalf. That includes
  **gate tags** — every `gate.py lock` mints a `gate-N/vN` tag that code repos consume as a
  submodule pin, and `git push` sends no tags (nor does `--follow-tags`: these are
  lightweight). After every lock: `git push && git push --tags`.
  Ask which the remote is for — durability only, or durability *and* hosted CI — and record the
  answer. It decides that last line here and step 4 of G5's repo checklist (`g5-first-slice.md`). The scaffold ships
  a `validate.yml` that does pass on a hosted runner, but the code repos' workflows will not
  (see the private-submodule trap in `g5-first-slice.md`), so "we push to GitHub" and "GitHub runs our CI" need to be
  separate decisions rather than one assumption.
  **Visibility follows the posture just decided.** `private-learning` or
  `possible-closed-distribution` → private, non-negotiable: pushing the rebuild to a public
  remote is distribution, which neither posture covers, and would need a G0 reopen. The
  mechanism differs by reference — a copyleft reference makes it a licensing problem, a
  proprietary one a terms/trade-secret problem — but the answer is private either way. Only
  `permissive-reference` leaves it open. Say this out loud when you create the repo —
  the user chose the posture minutes ago and will not connect it to a `gh` flag.
- Confirm the user can run the reference locally (Docker preferred; for a mobile reference,
  the old app installed on a real device or simulator, ideally from a backup of a real
  install). rspec's verify records its tests against it. **Record how it runs
  in `sources.yaml` `reference.run:`**: the compose files in order (an override for a missing
  secret or a port goes in a file outside the checkout, so the pinned tree stays clean; to replace
  a port list rather than add to it, the override needs `ports: !override`), the base URL, and how
  an agent gets an account (a shipped config may disable sign-up and anonymous use, as Kutt's
  does). Every brief points at that block, so a change is one edit.
- **Run the preflight, last, once everything above is filled in.** From the workbench root:
  ```sh
  python3 scripts/preflight.py                              # detect
  python3 scripts/preflight.py --run-build --run-tests   # …and execute the reference's own build/test commands
  ```
  It writes `PREFLIGHT.md` and `preflight.json`, with a verdict of **Ready**,
  **Ready-with-gaps** or **Not-ready**. This is the check that used to be the bullet above it:
  "confirm the user can run the reference" was a promise nothing verified. Every `[code]`
  citation in the spec cites `path + pinned_commit`, so a checkout sitting at a different
  commit writes citations that are wrong the moment they are written and stay wrong through
  a gate lock that hashes them. (Its per-lane line still names the 2.x lanes A–D: A is the
  docs and changelog, B and C the running product, D the code.)

  **A reference with no repository at all** (closed-source, SaaS) is accepted: leave
  `reference.repo`, `checkout` and `pinned_commit` empty and the source checks are skipped,
  with lane D `degraded` — docs, API and the running product only, as under posture `strict`. Fill
  any one of the three and the full check applies, so a repo you forgot to clone still fails.

  **Not-ready blocks rspec's discovery and nothing else.** `sources.yaml` and `license-posture.md`
  commit and push regardless — none of the causes changes a G0 decision, they change whether
  it is honest to start reading the reference. Fix the cause and re-run; it is idempotent.

  Executing the build and test commands is opt-in (`--run-build`, `--run-tests`) because
  they are arbitrary commands out of a third party's CI, the same source every agent brief
  treats as untrusted input. Detected-but-not-executed is recorded as a gap and named as
  unproven, never as a pass — so `Ready-with-gaps` is the right verdict for a reference
  whose build nobody has watched succeed.
- **Say what G5 will do to a code repo**, so the user hears it at the start rather than at the
  first lane: the repo is created by this plugin's `scaffold-repo` skill from the locked
  playbook's scaffold manifest, then set up for sdlc, which this plugin depends on (no stack is
  invented at G5: Gate 3 refuses a playbook with no manifest). Each lane is then an sdlc feature,
  and the guards of both plugins run for every lane, including a spec gate that blocks large edits
  until the lane's sdlc record carries the approval. The pipeline writes each lane's record from the
  slice specs the user approves. That approval is the one the gate checks, and no second approval
  is asked for (`g5-build.md` step 1b). sdlc then reviews each lane after it is built, by sdlc's own
  table (step 4b). Say too that the scaffold is a skeleton whose five commands pass on day one, not a
  feature kit: the first slice builds the first real module.

## Exit criteria
Reference chosen with recorded rationale; `license-posture.md` complete;
`sources.yaml` reviewed by the user, including `reference.kind`, `reference.upstream`, and
the `architecture:` block (playbook + target shape); workbench scaffolded and CI green on empty state;
workbench pushed to a remote whose visibility matches the recorded posture
(`python3 scripts/pause_check.py` confirms nothing is still local-only); **`PREFLIGHT.md` reads Ready
or Ready-with-gaps** (`python3 scripts/preflight.py` — Not-ready holds rspec's discovery, and only that).
