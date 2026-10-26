# Architecture playbook registry

One file per playbook. A project picks one at G0 (`sources.yaml` → `architecture.playbook`),
G4a vendors it to the workbench at `adr/playbook.md`, and Gate 3 hashes that copy along with
the ADRs. The pipeline knows nothing about any playbook's content — it reads the frontmatter.

| Playbook | Target shape | Stack | Scaffold manifest |
|---|---|---|---|
| `web-modular-monolith` (org default) | `fullstack` | Go + Nuxt modular monolith, API-first; Fastify + Next.js alternate | `web-modular-monolith/scaffold.json`: Go or Fastify (api), Nuxt or Next (web) |
| `mobile-flutter` | `client-only` | Flutter client against an existing HTTP API; Riverpod + go_router + Drift + generated dio client | `mobile-flutter/scaffold.json`: Flutter with Riverpod and `custom_lint` |

`web-modular-monolith` is the default when `architecture.playbook` is empty. `none` disables
the mechanism: every G4a ADR becomes a blank-slate decision against the reference alone, and the project
writes its own `adr/scaffold.json` (the same format, below) beside its stack ADR. Gate 3 checks it like a
registered playbook's and refuses to lock without a valid one.

## Writing your own

A playbook is a normal Markdown document with one required frontmatter block. Put it either
here (to share across projects) or inside the workbench (to keep it project-local, in which
case `architecture.playbook` holds its path rather than its name).

```yaml
---
playbook: my-playbook          # must match architecture.playbook exactly
stack: "one line, for the Gate 3 review"
target-shape: fullstack        # fullstack | client-only
scaffold: my-playbook/scaffold.json   # the manifest, relative to this file; `none` fails Gate 3
not-applicable-when:
  - "the criteria under which this playbook is the wrong choice"
concerns:
  authn-authz: "§7"            # concern key -> the section(s) that answer it
  data-modeling: "N/A"         # or N/A, where this playbook has no answer
decide-before:
  offline-sync: "local-persistence, api-client"   # decide the values before the key
---
```

Five rules the tooling enforces, and one it cannot:

1. **`concerns:` is the ADR list.** Every key needs an ADR before Gate 3 can lock, and every
   ADR names its key in a `concern:` field. This is what makes "every concern decided" a
   check instead of a sentence. Choose keys deliberately: a concern you leave out is a
   decision nobody will be asked to make.
2. **Section tokens are the citation vocabulary.** An ADR may only cite a `§` that appears
   somewhere in your `concerns:` map. Keep the map and the section bodies in sync — renumbering
   one without the other silently re-points every ADR that cited it.
3. **A playbook that cannot scaffold fails Gate 3.** `scaffold:` names a JSON manifest (below), vendored
   beside the playbook at G4a and locked with it. Missing, unreadable or `none` is refused at the gate, not at G5.
4. **`target-shape:` must match the project's.** Validation fails on a mismatch rather than
   letting a fullstack playbook govern a client-only rebuild.
5. **`N/A` is a real answer, not a gap.** It says "this playbook deliberately has no standing
   answer here, decide it against the reference" — which is different from forgetting the
   concern, and reads differently in a Gate 3 review.

What no check can do: tell you a section that *looks* right is the right one. §8 means storage
in one playbook and auth in another, and a plausible wrong citation passes every check there
is. That is why the chosen playbook is vendored into the workbench and locked, rather than
referenced from here.

**Keep the frontmatter simple.** It is parsed by a zero-dependency line reader (`gate.py`
runs with nothing but the standard library and its sibling scripts), so scalars, one list, and two
single-level maps are all it supports — no anchors, no folded scalars, no flow mappings. That is
why the scaffold manifest is a separate JSON file and not a nested block in the frontmatter.

## The scaffold manifest

One JSON file per playbook, beside it (`<playbook>/scaffold.json`), with the files it seeds under
`<playbook>/templates/`. `scripts/playbook.py` checks it at G4a and at Gate 3 with the same function
`scaffold-repo` reads it through, so what the gate accepts is exactly what G5 can run.

```json
{
  "ask":   [{"key": "org", "prompt": "Who owns the repos?", "suggest": "<your-github-org>"}],
  "rules": ["code-style", "tests", "migrations", "sensitive", "ci"],
  "ci":    {"os": ["ubuntu-latest"]},
  "packages": [{
    "name": "api", "path": ".", "monorepoPath": "apps/api",
    "options": {
      "go": {
        "generator": ["go mod init github.com/{{org}}/{{repo}}{{subpath}}"],
        "after":     ["go get github.com/gin-gonic/gin@latest", "go mod tidy"],
        "files":     [{"from": "go/main.go", "to": "cmd/api/main.go", "class": "seeded"}],
        "commands":  {"install": "go mod download", "build": "go build -o bin/ ./...",
                      "lint": "golangci-lint run ./...", "typecheck": "go vet ./...",
                      "test": "go test ./...", "test_fast": "go test -short ./..."},
        "ci":        {"setup": "go"}
      }
    }
  }]
}
```

- **`options`** is one entry per stack the playbook supports for that package. Which one a project
  uses is answered from the locked stack ADR, never at scaffold time.
- **`generator`** runs in the (empty) package directory, so it targets `.`; **`after`** runs once
  the `files` are written (install steps, a `tidy`). Both are shell lines.
- **`commands`** are the five every package must define (`install build lint typecheck test`), each
  a string or `null` where the stack has no such step. `test_fast` is optional and is what the git
  pre-commit hook runs. The day-one run executes all five, so a command that does not work
  is found when the repo is created.
- **Placeholders.** `{{key}}` in commands and paths: your `ask` keys plus `name`, `path`, `repo`,
  `subpath` (empty for a polyrepo, `/apps/api` for a monorepo). `[[key]]` in file *content*, so that
  Go and Vue templates keep their own `{{ }}`; any `[[...]]` that is not a known key is left as written.
- **`files[].class`**: `seeded` (rewritten only while untouched), `generated` (rewritten freely, and
  replaces a file the generator also writes), `user` (written once).
- **`files[]` entries** need `to` (a path that must stay inside the repo), a `class`, and exactly one of
  `from` (a template under `<playbook>/templates/`) or `content` (the text inline).
- **`generator`** may be empty only when `files` supply the skeleton. An option with neither has no skeleton
  and the check refuses it.
- **`ci`**: the top-level `ci.os` is the runner list. Per option, `ci.setup` is `go`, `node`, `flutter` or
  `none` (`none` writes a `TODO` line in the workflow, since no toolchain action is known), `ci.version` is the
  Node version for `node` (default `22`), and `ci.pre` is a list of shell lines the workflow runs before the five
  commands.
- Keep it a skeleton: the generator's output, strict typing, a runner, a linter, one passing smoke
  test. The first slice builds the first module.
