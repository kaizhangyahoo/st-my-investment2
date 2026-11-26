"""Store of the instrument-name -> ticker map, owned by reference-data from P3 on.

The file is shared with the legacy Streamlit app and is also hand-edited, so a read is a
boundary: anything that is not a flat `{name: ticker}` object is treated as an empty map rather
than allowed to propagate. The TTL cache that keeps hot paths off the disk is deliberately *not*
here -- it lives on `ticker_service.load_ticker_mappings`, because `backend.app.core.cache.ttl_cache` keys
on the function's name and arguments, and a bound method would put `self` (whose default repr
embeds a memory address) in the key and miss on every call.
"""
import json
import logging
import os
from typing import Dict

from backend.app.core.config import settings
from backend.app.core.json_store import write_json_atomically

logger = logging.getLogger(__name__)


class TickerMapStore:
    @property
    def path(self) -> str:
        return settings.TICKER_MAP_FILE

    def read(self) -> Dict[str, str]:
        path = self.path
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            logger.warning(
                "Could not read %s: %s. Treating the ticker map as empty, which leaves every "
                "instrument unresolved until the file is readable again.",
                path,
                e,
            )
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, mappings: Dict[str, str]) -> None:
        """Replace the whole map. Merging is the caller's job -- it owns the clash rules."""
        write_json_atomically(self.path, mappings, prefix=".company_name_to_ticker_")
