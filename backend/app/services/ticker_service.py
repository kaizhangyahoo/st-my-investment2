import os
import json
from typing import Dict, List, Optional
from backend.app.core.config import settings

def load_ticker_mappings() -> Dict[str, str]:
    filepath = settings.TICKER_MAP_FILE
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ticker_mappings(mappings: Dict[str, str]) -> Dict[str, str]:
    filepath = settings.TICKER_MAP_FILE
    current = load_ticker_mappings()
    current.update(mappings)
    with open(filepath, "w") as f:
        json.dump(current, f, indent=2)
    return current

def resolve_tickers_sec(market_names: List[str]) -> Dict[str, Optional[str]]:
    resolved: Dict[str, Optional[str]] = {}
    try:
        from rewrite_ticker_resolution import use_sec_site
        sec_resolved = use_sec_site(market_names)
        for name in market_names:
            resolved[name] = sec_resolved.get(name, None)
    except Exception:
        for name in market_names:
            resolved[name] = None
    return resolved

