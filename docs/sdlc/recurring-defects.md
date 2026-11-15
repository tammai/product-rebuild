# Recurring defects

One line per defect: what it looks like, then the severity.

- A check that returns "no problems" before it has read its input, so an unreadable file passes when there is nothing to compare against (validate.py over departures.yaml, 2026-11-09). High.
- A credential attached to a request before checking the host the client will really dial: urljoin lets `//host`, an absolute URL or a tab/CR/LF in the path replace the base host (equiv.py signed requests, 2026-11-09). High.
- A secret scan scoped to the current account, or run over serialised text where escaping hides a quote or backslash, instead of every configured credential against every decoded string (equiv.py traces, 2026-11-09). High.
- A "target is down" check that matches one runner's error wording (only "refused", only run-http) instead of asking the target again after any failed run, so reset, closed, timed-out, gateway 502 or Playwright failures of a dead build still become findings, and a step after the check runs against the dead build (boundary.py health guard, 2026-11-15). High.
- A guard that infers "a fix happened" from side signals (branch digests, file hashes) instead of a recorded attempt, so it counts unrelated changes and misses fixes elsewhere (route.py fix rounds, 2026-11-09). High.
