# [[repo]]

Rebuild code repo. Decisions, specs and contracts live in the rebuild workbench: [[workbench]].
It is set up for sdlc: the commands are in `.sdlc/config.json`, and each build lane is an sdlc feature
(`docs/sdlc/changes/`, `.sdlc/state/`). There, `test` is the fast suite; the full suite runs once per
slice, at the joint run:
[[full_tests]]
The product-rebuild and sdlc plugins' guards run on this repo; a block names its guard and why. Follow it, do not edit around it.
