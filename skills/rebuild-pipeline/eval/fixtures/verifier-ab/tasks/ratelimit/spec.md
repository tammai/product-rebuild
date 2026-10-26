# Per-key sliding-window rate limiter

Module `ratelimit`, file `ratelimit.py`, Python 3.9+, standard library only. The limiter never
reads a clock: callers pass `now`, a number of seconds that does not go backwards for a given key.

```python
RateLimiter(limit, window)
RateLimiter.check(key, now) -> (allowed: bool, retry_after: int)
RateLimiter.reset(key) -> None
```

## Acceptance criteria

1. [R-RL-001] At most `limit` requests are allowed per key in any sliding window of `window`
   seconds. An allowed request made at time `t` counts against the limit until `t + window`
   exactly: a request at `t + window` no longer sees it.
2. [R-RL-002] A denied request returns `(False, retry_after)`. `retry_after` is the whole number
   of seconds until the next request would be allowed, rounded up, and never less than 1. The next
   allowed time is the oldest counted request's time plus `window`.
3. [R-RL-003] An allowed request returns `(True, 0)`.
4. [R-RL-004] A denied request does not count against the limit and does not move any window.
5. [R-RL-005] Keys are independent. `reset(key)` forgets every request counted for that key, and
   resetting a key never seen is a no-op.
6. [R-RL-006] `limit` must be a positive integer and `window` a positive number (int or float);
   otherwise the constructor raises `ValueError("E-CONFIG")`.
