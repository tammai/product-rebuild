---
description: Run or resume the product rebuild pipeline (orchestrator)
---

Load the `rebuild-pipeline` skill and follow its Orchestration Protocol from the top:
detect pipeline state from the workbench `locks/` directory, report current phase and
progress to the user (a workbench with no `rebuild_major:` in `locks/pipeline.yaml` was made by a 0.x
release: say that this plugin will not open it, point the user at the 0.x line to finish it, and stop;
never offer a migration), then either continue the active phase, run the next gate review,
or ask the user what they want to do. Never skip state detection.

$ARGUMENTS
