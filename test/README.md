# Tests

Every suite here is Python, stdlib `unittest`, and runs **fully offline** — no provider is
ever contacted and no file in the repo is ever written.

## Running

Always run from the **repo root**. `backend` has no `__init__.py`, so it resolves as a
PEP 420 namespace package and only imports when the root is on `sys.path`; some suites
also import root-level modules such as `alpaca_client`.

```bash
python -m unittest                                          # everything
python -m unittest discover -s test/unitTest                # one bucket
python -m test.functionalTest.test_unresolved_symbol_gate    # one module
python -m unittest test.unitTest.test_ticker_resolution.TestResolveTicker.test_a_cyclic_chain_terminates
```

A bare `python -m unittest` discovers everything because every directory here is a real
package. That also makes `-t .` unnecessary — discovery walks up from the start directory
to find the root itself. Passing it anyway is harmless.

**`python test/unitTest/test_ticker_resolution.py` does not work** — it fails with
`ModuleNotFoundError: No module named 'backend'`, because running a file by path puts
`test/unitTest/` on `sys.path` instead of the root. The `if __name__ == "__main__"` blocks
are only reachable via `-m`.

## Install

```bash
pip install -r test/requirements.txt
```

This pulls in `backend/requirements.txt` plus `pytest` and `playwright`. The `test/`
suites need neither of the latter two — they are for the browser E2E examples (see below),
and they are **not currently installed** in `.venv`. Installing them is a real dependency
change on this network: the Artifactory mirror blocks or 403s some packages, so treat the
Playwright lines as declared intent rather than a verified working state. Browser binaries
are a separate step: `playwright install chromium`.

## Layout

```
test/
  unitTest/           one function or class, in isolation
  functionalTest/     a feature through its real entry point
  nonFunctionalTest/  performance and resilience guards
  support/            shared fixtures and stubs (not collected)
```

The bucket is spelled `unitTest`, not `unittest`, so it can never shadow the stdlib module.

### Which bucket?

| | Put a test here when it asserts… | Example |
|---|---|---|
| `unitTest` | the behaviour of one callable, with its collaborators replaced | `resolve_ticker` follows a mapping chain and stops on a cycle |
| `functionalTest` | that a user-visible feature is correct end to end, via the real handler and the real engine | an unmapped CSV name comes back on the `POST /trades/upload` response and its rows are the ones the engine drops |
| `nonFunctionalTest` | *how* the system behaves rather than *what* it returns — cost, latency, degradation | no `time.sleep` on the batch path; a 402-exhausted provider still yields a usable partial load |

`nonFunctionalTest` asserts on the *causes* of latency (sleep calls, request counts,
fan-out width) rather than wall-clock, so it stays deterministic on a loaded machine.

### Current coverage

| Module | Covers |
|---|---|
| `unitTest/test_ticker_resolution.py` | `resolve_ticker` — chains, multi-hop, cycles, absent/null/blank mappings |
| `unitTest/test_price_parsing.py` | EODHD zero-close → `previousClose`; TwelveData batch size |
| `unitTest/test_data_quality_contract.py` | the `data_quality` and `unresolved_symbols` payload shapes |
| `unitTest/test_alpaca_client.py` | `alpaca_client` request construction and error paths |
| `functionalTest/test_price_fallback_chain.py` | provider ordering: Yahoo first, paid providers only as top-up |
| `functionalTest/test_portfolio_data_quality.py` | the engine populates `degraded` / `fx_fallback` / `unpriced_tickers` |
| `functionalTest/test_unresolved_symbol_gate.py` | the KAN-12 gate: upload → skip/confirm → totals |
| `functionalTest/test_portfolio_history_endpoint.py` | KAN-19 — `GET /portfolio/history` computes from the upload instead of replaying the Streamlit file |
| `functionalTest/test_ohlc_endpoint_contract.py` | KAN-37/KAN-35 — `GET /market-data/ohlc/{ticker}` shape, NaN handling, and `get_ohlc` caching |
| `nonFunctionalTest/test_cold_load_performance.py` | KAN-18 latency guards — no blocking sleep, bounded fan-out, timeouts set |
| `nonFunctionalTest/test_provider_resilience.py` | EODHD quota exhaustion and FX fallback announce themselves |

## Isolation rules

These three are the whole reason the suite stays offline and side-effect-free. A new test
that gets any of them wrong will look like it passes while silently hitting the network or
rewriting a tracked file.

**1. Stub `price_service._session`, not `requests.get`.** All four HTTP call sites go
through the module-level `requests.Session()` at `backend/app/services/price_service.py:32`,
so patching `requests.get` intercepts nothing. Use `support.stubs.session_stub()`:

```python
session, calls = session_stub(yahoo=lambda url, kw: response(payload=yahoo_quote(200.0)))
with patch.object(price_service, "_session", session):
    ...
```

A host left as `None` means *must not be called* and raises `AssertionError`, which no
production `except` clause catches — so an unexpected provider call fails loudly instead of
being swallowed into a fallback.

**2. Patch the consumer's binding, not the producer.** `portfolio_engine` imports
`get_current_prices` / `get_historical_fx` by name, and they are wrapped in `ttl_cache` —
one module-level singleton with no `cache_clear()`. Patching
`portfolio_engine.get_current_prices` never enters the cache at all. Use
`support.portfolio.run_engine()`. When you must test `market_service` directly, call
`cache.clear()` in both `setUp` and `tearDown`.

**3. Subclass `support.portfolio.TempMappingCase` for anything that writes mappings.**
It redirects `settings.TICKER_MAP_FILE` at a temp file and **asserts the redirect took
effect**, so `save_ticker_mappings()` can never touch the repo's
`company_name_to_ticker.json`. The assertion matters: a silently-ignored `setattr` would
mean the test rewrites a tracked file. Override `MAPPINGS` to set the starting state.

## HTTP-level endpoint tests

`fastapi.testclient.TestClient` **does** work here, behind a `try/except ImportError` +
`@unittest.skipIf` guard so the suite still collects if `httpx` goes missing. Reach for it
when the assertion is about the HTTP response itself — a status code, or JSON serialisation,
where calling the handler directly returns a dict and would pass even on a payload that
cannot be encoded. `get_current_user` falls back to an anonymous dev user, so no token is
needed. Calling the handler directly is still fine, and cheaper, when the assertion is
about the returned value rather than the response.

## Not here

**Browser E2E** lives at `.agent/skills/playwright_testing/examples/`, run with
`pytest .agent/skills/playwright_testing/examples`. It stayed there deliberately:
`SKILL.md` references those paths, `test_login.py` does a sibling-relative
`from scripts.auth_helper import AuthHelper`, and the examples target the **legacy
Streamlit app on :8501** — not the FastAPI backend these suites cover.

**Frontend tests** — there are none; `frontend/` has no test runner configured.
