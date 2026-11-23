import time
from typing import Any, Callable, Dict, Optional, Tuple
from functools import wraps
import threading

from backend.app.core.tracing import (
    record_cache_hit,
    record_cache_miss,
    record_cache_uncacheable,
)

# Tells "no entry" apart from "an entry whose value is None". Overloading None with both
# meanings left a decorated function no way to refuse caching except to return None, so a
# failure that came back as a value instead -- an empty frame, an approximated rate -- was
# stored and then served for the whole TTL (KAN-53).
MISS = object()

class TTLCache:
    def __init__(self, default_ttl: int = 3600):
        self.default_ttl = default_ttl
        self._store: Dict[Any, Tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            if key in self._store:
                val, expires_at = self._store[key]
                if time.time() < expires_at:
                    return val
                del self._store[key]
            return default

    def set(self, key: Any, val: Any, ttl: Optional[int] = None) -> None:
        ttl_val = ttl if ttl is not None else self.default_ttl
        with self._lock:
            self._store[key] = (val, time.time() + ttl_val)

    def delete(self, key: Any) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

cache = TTLCache(default_ttl=3600)

def ttl_cache(
    ttl: int = 3600,
    cache_if: Optional[Callable[[Any], bool]] = None,
    name: Optional[str] = None,
):
    """Memoise `func` on its arguments for `ttl` seconds.

    `cache_if` decides whether a result is worth keeping, and is the only way to say "do not
    cache this". Providers here fail by returning a value rather than raising, so without it a
    one-second outage becomes an hour-long one: the failure occupies the key and the next
    request is answered from it instead of retrying. A successful-but-empty answer -- a
    delisted ticker -- is a real answer and must still cache, so the predicate belongs at the
    decoration site where the difference is known, not in here.

    `name` is what the lookups are counted under on the enclosing span, and is worth stating at
    the decoration site: defaulting to `func.__name__` would publish `cache._fetch_ohlc.hits`
    in Tempo, a private identifier that renames whenever the function does.
    """
    def decorator(func: Callable):
        counter = name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (func.__name__, str(args), str(sorted(kwargs.items())))
            cached_res = cache.get(key, MISS)
            if cached_res is not MISS:
                record_cache_hit(counter)
                return cached_res
            record_cache_miss(counter)
            res = func(*args, **kwargs)
            if cache_if is None or cache_if(res):
                cache.set(key, res, ttl=ttl)
            else:
                record_cache_uncacheable(counter)
            return res

        def clear(*c_args, **c_kwargs):
            """Invalidate all cached entries for this function, or a specific call signature."""
            if not c_args and not c_kwargs:
                with cache._lock:
                    keys = [k for k in cache._store if isinstance(k, tuple) and len(k) > 0 and k[0] == func.__name__]
                    for k in keys:
                        del cache._store[k]
            else:
                key = (func.__name__, str(c_args), str(sorted(c_kwargs.items())))
                cache.delete(key)

        wrapper.clear = clear
        wrapper.invalidate = clear
        return wrapper
    return decorator

