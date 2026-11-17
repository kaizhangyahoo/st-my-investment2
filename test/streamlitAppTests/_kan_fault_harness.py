"""Streamlit wrapper that runs rewrite_tab_1.py with provider faults injected.

The happy-path E2E never reaches the branches KAN-21/22/23 live, because EODHD had
quota left and Yahoo answered for every ticker. This harness forces those branches
through the real dashboard with the real CSVs.

Scenario is chosen with KAN_SCENARIO:

  A  EODHD returns 402 for everything, and Yahoo fails for PAY.L.
     -> exercises the 402 fallback (KAN-21: float + correct unit for AFX.DE/PAY.L)
        and the Yahoo per-symbol failure path (KAN-22).

  B  Yahoo historical fails for a held ticker (KOPN) while EODHD returns a price.
     -> exercises _fetch_eodhd_synthetic_data with LastDate=None (KAN-23).

Run exactly like the app:
  KAN_SCENARIO=A streamlit run _kan_fault_harness.py
"""
import json
import os
import traceback

import requests

import getEODprice
import market_data_api

try:
    import historical_market_data           # post-KAN-15 location
except ImportError:                         # pre-refactor tree: lived in market_data_api
    historical_market_data = market_data_api

SCENARIO = os.environ.get("KAN_SCENARIO", "A").upper()
YAHOO_FAIL = {"A": {"PAY.L"}, "B": {"KOPN"}, "C": set()}[SCENARIO]

# Streamlit does not capture the script thread's stdout, so evidence goes to a file.
# Streamlit also re-executes this script on every widget interaction, so the file is
# only ever appended to (cleared by the caller before the run) and every patch below
# is applied once, guarded by a marker on the long-lived imported module.
EVIDENCE = f"/tmp/kan_evidence_{SCENARIO}.jsonl"


def record(**fields):
    with open(EVIDENCE, "a") as fh:
        fh.write(json.dumps(fields, default=repr) + "\n")


_ALREADY_PATCHED = getattr(getEODprice, "_kan_harness_installed", False)

# ── Record what the EODHD entry point actually returns, and in what type ──
if not _ALREADY_PATCHED:
    _real_eodhd = getEODprice.getEODpriceFromEODHD

    def _recording_eodhd(symbol_or_symbols, *args, **kwargs):
        try:
            result = _real_eodhd(symbol_or_symbols, *args, **kwargs)
        except Exception as exc:
            record(event="eodhd_raised", arg=symbol_or_symbols, error=repr(exc),
                   tb=traceback.format_exc()[-600:])
            raise
        record(event="eodhd_return", arg=symbol_or_symbols,
               result=result, result_type=type(result).__name__)
        return result

    getEODprice.getEODpriceFromEODHD = _recording_eodhd

    # getEODpriceUK / _yahoo_last_closes carry the KAN-21 unit decision, so record them.
    _real_uk = getEODprice.getEODpriceUK

    def _recording_uk(symbols):
        result = _real_uk(symbols)
        record(event="yahoo_last_closes", divisor=100, arg=list(symbols),
               result=result, result_type=type(result).__name__)
        return result

    getEODprice.getEODpriceUK = _recording_uk

    # _yahoo_last_closes only exists post-fix; pre-fix the logic sat inside getEODpriceUK.
    if hasattr(getEODprice, "_yahoo_last_closes"):
        _real_closes = getEODprice._yahoo_last_closes

        def _recording_closes(symbols, divisor):
            result = _real_closes(symbols, divisor)
            record(event="yahoo_last_closes", divisor=divisor, arg=list(symbols),
                   result=result, result_type=type(result).__name__)
            return result

        getEODprice._yahoo_last_closes = _recording_closes

# ── Fail Yahoo for selected symbols, patched on the class so every import sees it ──
if not _ALREADY_PATCHED:
    _real_yahoo = market_data_api.OHLC_YahooFinance.yahooDataV8

    def _patched_yahoo(self):
        if self.symbol in YAHOO_FAIL:
            record(event="yahoo_forced_failure", symbol=self.symbol)
            raise requests.RequestException(f"harness: simulated 503 for {self.symbol}")
        return _real_yahoo(self)

    market_data_api.OHLC_YahooFinance.yahooDataV8 = _patched_yahoo

if not _ALREADY_PATCHED and SCENARIO in ("A", "C"):
    # ── Force EODHD to 402 (quota exhausted), leaving every other host untouched ──
    _real_get = requests.get

    def _patched_get(url, *args, **kwargs):
        if "eodhd.com" in str(url):
            record(event="eodhd_forced_402", url=str(url).split("?")[0])
            resp = requests.Response()
            resp.status_code = 402
            resp._content = b"Daily request limit reached"
            return resp
        return _real_get(url, *args, **kwargs)

    requests.get = _patched_get
    getEODprice.requests.get = _patched_get

elif not _ALREADY_PATCHED and SCENARIO == "B":
    # ── Keep EODHD answering so the synthetic path reaches bdate_range ──
    def _stub_eodhd(symbol_or_symbols, *args, **kwargs):
        # Honour the real contract: a dict for list input (get_current_price), a float
        # for a single symbol (_get_eodhd_single_price, which feeds the synthetic path).
        # Stubbed rather than delegated so both trees see identical input: the live 402
        # would otherwise drag KAN-21's own bug into this KAN-23 comparison.
        if isinstance(symbol_or_symbols, (list, tuple, set)):
            record(event="eodhd_stub_prices", symbols=list(symbol_or_symbols), price=3.21)
            return {s: 3.21 for s in symbol_or_symbols}
        record(event="eodhd_stub_price", symbol=symbol_or_symbols, price=3.21)
        return 3.21

    # Post-fix imports this at module scope; pre-fix imports it inside the method.
    # Patch both so the stub lands whichever tree is running.
    getEODprice.getEODpriceFromEODHD = _stub_eodhd
    historical_market_data.getEODpriceFromEODHD = _stub_eodhd

getEODprice._kan_harness_installed = True
record(event="script_run", scenario=SCENARIO, yahoo_fail=sorted(YAHOO_FAIL),
       first_run=not _ALREADY_PATCHED)

exec(open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                       "rewrite_tab_1.py")).read())
