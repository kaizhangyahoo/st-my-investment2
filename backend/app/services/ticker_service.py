from collections import Counter
from typing import Any, Dict, List, Optional

from backend.app.stores.ticker_map import TickerMapStore
from backend.app.core.cache import ttl_cache
from backend.app.core.config import settings

_store = TickerMapStore()

# Cached for 300 seconds (5 minutes) so that redundant file I/O on hot paths
# (e.g. GET /api/v1/trades/summary) is avoided, while manual edits made directly
# to company_name_to_ticker.json on disk become visible within 5 minutes without
# requiring a process restart. Writes through save_ticker_mappings() invalidate
# the cache immediately.
TICKER_MAP_TTL = 300


# The cache stays on this module-level function rather than moving onto the store: `ttl_cache`
# keys on the function name and the stringified arguments, so a bound method would put `self` --
# and its address-bearing default repr -- in the key and miss on every call. `name` is also the
# prefix of the `cache.ticker_map.*` span attributes, so it must not drift.
@ttl_cache(ttl=TICKER_MAP_TTL, name="ticker_map")
def load_ticker_mappings() -> Dict[str, str]:
    # Split mode: data-api owns the file, so portfolio-api reads it over HTTP. Same cache, TTL
    # and span attributes either way -- only the body moved.
    if settings.DATA_API_URL:
        from backend.app.services import data_client
        return data_client.fetch_ticker_mappings()
    return _store.read()


def resolve_ticker(raw_name: str, mappings: Dict[str, str]) -> Optional[str]:
    """
    Resolve a broker instrument name to its current ticker, following
    ticker -> ticker remap entries left behind by corporate actions
    (e.g. "Skillz Inc" -> "SKLZ" -> "FIRY").
    """
    ticker = mappings.get(raw_name)
    # A blank mapping is unresolved, not a ticker. Without this the engine would
    # group trades under an empty ticker and invent a phantom position.
    if ticker is None or not str(ticker).strip():
        return None
    seen = {raw_name}
    while ticker in mappings and ticker not in seen:
        seen.add(ticker)
        ticker = mappings[ticker]
    if not str(ticker).strip():
        return None
    return ticker


def find_unresolved_symbols(market_names: List[str]) -> List[Dict[str, Any]]:
    """
    Given every Market value in a trade history (including repeats), return the
    distinct names that cannot be resolved to a ticker, with how many rows each
    one affects. Uses resolve_ticker so the result always matches the rows the
    portfolio engine drops.
    """
    mappings = load_ticker_mappings()
    counts = Counter(name for name in market_names if str(name).strip())
    unresolved = [
        {"market_name": name, "row_count": count}
        for name, count in counts.items()
        if resolve_ticker(name, mappings) is None
    ]
    unresolved.sort(key=lambda item: (-item["row_count"], item["market_name"]))
    return unresolved


def _fold(name: str) -> str:
    """Comparison key for spotting near-duplicate names: case and whitespace runs ignored."""
    return " ".join(name.split()).casefold()


def normalise_mappings(mappings: Dict[str, str]) -> Dict[str, str]:
    """
    Validate a mapping payload before it reaches disk. Tickers are trimmed and
    uppercased; names are kept verbatim because they must match the broker's
    Market string exactly. Raises ValueError on a blank name or ticker, or on two
    names that differ only by case/whitespace.
    """
    clean: Dict[str, str] = {}
    seen: Dict[str, str] = {}
    for name, ticker in mappings.items():
        if not name.strip():
            raise ValueError("Mapping name cannot be blank")
        ticker = (ticker or "").strip().upper()
        if not ticker:
            raise ValueError(f'Ticker for "{name}" cannot be blank')
        clash = seen.get(_fold(name))
        if clash is not None:
            raise ValueError(f'"{name}" duplicates "{clash}"')
        seen[_fold(name)] = name
        clean[name] = ticker
    return clean


def save_ticker_mappings(mappings: Dict[str, str], replace: bool = False) -> Dict[str, str]:
    """
    Merge `mappings` into the stored map, or with `replace=True` make it the whole
    map -- the only way a delete or rename reaches the file.
    """
    clean = normalise_mappings(mappings)
    current = {} if replace else dict(load_ticker_mappings())
    existing = {_fold(name): name for name in current}
    for name in clean:
        clash = existing.get(_fold(name))
        if clash is not None and clash != name:
            raise ValueError(f'"{name}" duplicates existing mapping "{clash}"')
    current.update(clean)
    _store.write(current)
    load_ticker_mappings.clear()
    return current

def resolve_tickers_sec(market_names: List[str]) -> Dict[str, Optional[str]]:
    resolved: Dict[str, Optional[str]] = {}
    try:
        from shared_service.ticker_resolution import use_sec_site
        sec_resolved = use_sec_site(market_names)
        for name in market_names:
            resolved[name] = sec_resolved.get(name, None)
    except Exception:
        for name in market_names:
            resolved[name] = None
    return resolved

