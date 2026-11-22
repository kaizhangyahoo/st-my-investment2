"""A token bucket, used to stop a browser render loop flooding the telemetry route.

In-process and therefore per-instance: under Cloud Run autoscaling the effective limit is
this budget times the instance count. That is acceptable for shedding a runaway client,
which is all this is for, and the backend is not deployed yet regardless.
"""
import threading
import time
from typing import Dict, Tuple


class TokenBucket:
    # Beyond this many tracked clients, full (i.e. idle) buckets are forgotten -- a forgotten
    # key restarts full, so dropping one changes nothing but memory.
    _MAX_KEYS = 10_000

    def __init__(self, capacity: int, refill_seconds: float) -> None:
        self.capacity = capacity
        self.refill_rate = capacity / refill_seconds
        self._state: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._state) > self._MAX_KEYS:
                self._prune(now)
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_rate)
            if tokens < 1.0:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1.0, now)
            return True

    def _prune(self, now: float) -> None:
        full_after = self.capacity / self.refill_rate
        self._state = {k: v for k, v in self._state.items() if now - v[1] < full_after}

    def reset(self) -> None:
        with self._lock:
            self._state.clear()
