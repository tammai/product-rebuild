<!-- Managed by the sdlc plugin v3.2.1. Regenerated on /sdlc:upgrade: edits here are lost. Files named sdlc-*.md belong to the plugin; put your own rules in CLAUDE.md or other .claude/rules/ files. -->
# SDLC workflow

- Start or resume work with `/sdlc:start <request>`; check progress with `/sdlc:status`. A feature's documents live in `docs/sdlc/intents/<feature>/` and its state in `.sdlc/state/` (both committed; `scaffold.py paths <feature>` names them); scratch goes in `.sdlc/.work/` (git-ignored).
- The project's commands are in `.sdlc/config.json`: `commands` (install, test, lint, typecheck, build), or per package under `packages` in a monorepo. Use them exactly as written, from the package's directory; don't invent other invocations.
- A full test run is that `test` command with no filters (no file, name or package arguments). In a monorepo each package has its own, run from its `path`; only that package's results go fresh.
- Known pre-existing failures are listed in `.sdlc/baseline.md`; only new failures block Review.
- Project principles: `docs/sdlc/constitution.md`. Team knowledge: open `knowledge/index.md` and follow links on demand; don't read the folder wholesale.
