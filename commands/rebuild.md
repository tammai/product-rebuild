---
description: Run or resume the product rebuild pipeline (orchestrator)
---

Load the `rebuild-pipeline` skill and follow its Orchestration Protocol from the top:
detect pipeline state from the workbench `locks/` directory, report current phase and
progress to the user (a workbench whose `locks/pipeline.yaml` does not say `rebuild_major: 3` was made by
an older release: say that this plugin will not open it, point the user at the release to finish it on
(2.x: product-rebuild 2.2.0), and stop; never offer a migration), then either continue the active phase, run the next gate review,
or ask the user what they want to do. Never skip state detection.

$ARGUMENTS
