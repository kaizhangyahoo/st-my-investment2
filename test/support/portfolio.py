"""Trade-history fixtures and an offline portfolio-engine runner.

Two isolation rules make these fixtures safe to reuse:

1. `TempMappingCase` redirects `settings.TICKER_MAP_FILE` to a per-test temp file, so
   `save_ticker_mappings()` can never write the repo's `company_name_to_ticker.json`.
   setUp asserts the redirect took -- `settings` is a pydantic model, and a
   silently-ignored setattr would mean every test mutated the real mapping file.
2. `run_engine` patches prices and FX on the `portfolio_engine` bindings rather than on
   `market_service`, which sidesteps the module-level `ttl_cache` singleton and keeps
   every provider offline.

Ticker resolution is deliberately NOT patched here: callers of these fixtures are
testing it, and it runs against the temp mapping file.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import pandas as pd

from backend.app.core.config import settings
from backend.app.services import portfolio_engine

# "Apple Inc" is mapped; "Bogus Ltd" is not, and owns 2 of the 3 rows.
TRADE_CSV = (
    "Market,Quantity,Cost/Proceeds,Charges,Commission,Currency,Date\n"
    "Apple Inc,10,-1000.0,0.0,0.0,USD,2024-01-02\n"
    "Bogus Ltd,5,-500.0,-1.0,0.0,GBP,2024-01-03\n"
    "Bogus Ltd,3,-300.0,0.0,0.0,GBP,2024-01-04\n"
)

PRICES = {"AAPL": 200.0, "BOGUS.L": 7.0, "FIRY": 2.0}

# AAPL   : 10 x 200 = 2000 USD / 1.25 = 1600.00 GBP, costs -1000.00 -> P&L +600.00
# BOGUS.L:  8 x   7 =            56.00 GBP (.L is already GBP), costs  -801.00 -> P&L -745.00
GBPUSD, GBPEUR = 1.25, 1.15


def trade_df(csv_text=TRADE_CSV):
    df = pd.read_csv(io.StringIO(csv_text))
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def run_engine(df, prices=PRICES):
    fx = ({"GBPUSD=X": pd.Series([GBPUSD]), "GBPEUR=X": pd.Series([GBPEUR])}, False)
    with ExitStack() as stack:
        for target, new in (
            ("get_current_prices", lambda tickers: ({t: prices.get(t) for t in tickers}, [])),
            ("get_historical_fx", lambda start: fx),
        ):
            stack.enter_context(patch.object(portfolio_engine, target, new))
        return portfolio_engine.calculate_positions_from_df(df)


class TempMappingCase(unittest.TestCase):
    """Base case that points the ticker map at a throwaway file."""

    MAPPINGS = {"Apple Inc": "AAPL"}

    def setUp(self):
        fd, self.map_path = tempfile.mkstemp(prefix="verify_ticker_map_", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(self.MAPPINGS, f)
        self.addCleanup(os.unlink, self.map_path)
        patcher = patch.object(settings, "TICKER_MAP_FILE", self.map_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(settings.TICKER_MAP_FILE, self.map_path)
