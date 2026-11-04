import time
from typing import Any, Callable, Dict, Tuple
from functools import wraps
import threading

class TTLCache:
    def __init__(self, default_ttl: int = 3600):
        self.default_ttl = default_ttl
        self._store: Dict[Any, Tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        with self._lock:
            if key in self._store:
                val, expires_at = self._store[key]
                if time.time() < expires_at:
                    return val
                del self._store[key]
            return None

    def set(self, key: Any, val: Any, ttl: Optional[int] = None) -> None:
        ttl_val = ttl if ttl is not None else self.default_ttl
        with self._lock:
            self._store[key] = (val, time.time() + ttl_val)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

cache = TTLCache(default_ttl=3600)

def ttl_cache(ttl: int = 3600):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (func.__name__, str(args), str(sorted(kwargs.items())))
            cached_res = cache.get(key)
            if cached_res is not None:
                return cached_res
            res = func(*args, **kwargs)
            cache.set(key, res, ttl=ttl)
            return res
        return wrapper
    return decorator

