"""Trade-history and transaction-statement fixtures, plus an offline portfolio-engine runner.

Three isolation rules make these fixtures safe to reuse:

1. `TempMappingCase` redirects `settings.TICKER_MAP_FILE` to a per-test temp file, so
   `save_ticker_mappings()` can never write the repo's `company_name_to_ticker.json`.
   setUp asserts the redirect took -- `settings` is a pydantic model, and a
   silently-ignored setattr would mean every test mutated the real mapping file.
2. `run_engine` patches prices and FX on the `portfolio_engine` bindings rather than on
   `market_service`, which sidesteps the module-level `ttl_cache` singleton and keeps
   every provider offline.
3. `temp_fx_store` does the same for `settings.FX_HISTORY_FILE`, which any test that reaches
   `get_historical_fx` for real must use.

Ticker resolution is deliberately NOT patched here: callers of these fixtures are
testing it, and it runs against the temp mapping file.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from typing import Optional
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

# Shape of a real IG TransactionHistory export: amounts >= 1,000 carry a thousands separator,
# `PL Amount` is already signed, every row is GBP, and both a `DateUtc` and a `TextDate` are
# present. Opens with the founding deposit, so the running balance never goes negative and the
# ledger reads as reaching account inception.
TRANSACTION_CSV = (
    "TextDate,Summary,MarketName,PL Amount,Cash transaction,DateUtc,CurrencyIsoCode\n"
    '01/04/19,Cash In,Bank Deposit,"5,000.00",false,2019-04-01T09:15:00,GBP\n'
    '02/04/19,Client Consideration,Lam Research Corp CONS 2@100,"-2,000.00",false,2019-04-02T10:00:00,GBP\n'
    "03/04/19,Dividend,Lam Research Corp DIVIDEND 2@33.77,67.55,false,2019-04-03T11:30:00,GBP\n"
    "04/04/19,Share Dealing Commissions,Lam Research Corp COMM,-10.00,false,2019-04-04T11:30:00,GBP\n"
    '05/04/19,Client Consideration,Lam Research Corp CONS 1@150,"1,500.00",false,2019-04-05T14:45:00,GBP\n'
)

# 5000.00 - 2000.00 + 67.55 - 10.00 + 1500.00
TRANSACTION_BALANCE = 4557.55


def transaction_df(csv_text=TRANSACTION_CSV):
    return pd.read_csv(io.StringIO(csv_text))

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


def fx_frame(rate, dates=("2024-01-02",)):
    """A frame shaped like `fetch_yahoo_history`'s: a normalised `Date` column, indexed by it.

    Stubbing a bare `close` column instead would pass a fetcher that cannot read a real
    response, since the dates are what the FX store is keyed on.
    """
    df = pd.DataFrame({"Date": pd.to_datetime(list(dates)), "close": [rate] * len(dates)})
    df.index = df["Date"]
    return df


def temp_fx_store(case: unittest.TestCase, seed: Optional[dict] = None) -> str:
    """Point `settings.FX_HISTORY_FILE` at a throwaway path for the rest of `case`.

    `get_historical_fx` persists every real close it fetches, and the default path is the repo's
    own `fx_history.json`. A test that drives it without this would seed the developer's store
    with stub rates, read them back on the next run, and so stop testing what it says it does.
    `seed` writes a starting store, which is how an outage with usable history is set up.
    """
    directory = tempfile.mkdtemp(prefix="verify_fx_store_")
    store_path = os.path.join(directory, "fx_history.json")
    if seed is not None:
        with open(store_path, "w") as f:
            json.dump(seed, f)
    patcher = patch.object(settings, "FX_HISTORY_FILE", store_path)
    patcher.start()
    case.addCleanup(patcher.stop)
    case.assertEqual(settings.FX_HISTORY_FILE, store_path)
    return store_path


class TempMappingCase(unittest.TestCase):
    """Base case that points the ticker map at a throwaway file."""

    MAPPINGS = {"Apple Inc": "AAPL"}

    def setUp(self):
        from backend.app.services.ticker_service import load_ticker_mappings

        load_ticker_mappings.clear()
        self.addCleanup(load_ticker_mappings.clear)
        fd, self.map_path = tempfile.mkstemp(prefix="verify_ticker_map_", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(self.MAPPINGS, f)
        self.addCleanup(os.unlink, self.map_path)
        patcher = patch.object(settings, "TICKER_MAP_FILE", self.map_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(settings.TICKER_MAP_FILE, self.map_path)
