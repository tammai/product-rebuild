import math


class RateLimiter:
    def __init__(self, limit, window):
        if type(limit) is not int or limit <= 0 or isinstance(window, bool) \
                or not isinstance(window, (int, float)) or window <= 0:
            raise ValueError("E-CONFIG")
        self._limit, self._window, self._hits = limit, window, {}

    def check(self, key, now):
        hits = [t for t in self._hits.get(key, []) if t + self._window > now]
        if len(hits) < self._limit:
            hits.append(now)
            self._hits[key] = hits
            return (True, 0)
        self._hits[key] = hits
        return (False, max(1, math.ceil(hits[0] + self._window - now)))

    def reset(self, key):
        self._hits.pop(key, None)
