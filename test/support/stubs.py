"""HTTP stubs for the market-data providers.

All four of `price_service`'s HTTP call sites go through the module-level
`requests.Session()` at `price_service.py:32`, so patching `requests.get` would NOT
intercept them and a suite written that way would hit live providers. Patch
`price_service._session` with `session_stub()` instead.
"""
from unittest.mock import MagicMock

YAHOO_HOST = "query1.finance.yahoo.com"
EODHD_HOST = "eodhd.com"
TWELVEDATA_HOST = "api.twelvedata.com"


def response(status=200, payload=None, raise_exc=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {} if payload is None else payload
    resp.raise_for_status.side_effect = raise_exc
    return resp


def yahoo_quote(price, currency="USD"):
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "currency": currency}}]}}


def session_stub(yahoo=None, eodhd=None, twelvedata=None):
    """A stubbed Session.get that answers by provider host and records every URL it saw.

    A host left as None is treated as "must not be called" and raises AssertionError,
    which no production `except` clause catches, so the test fails loudly.
    """
    handlers = {YAHOO_HOST: yahoo, EODHD_HOST: eodhd, TWELVEDATA_HOST: twelvedata}
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        for host, handler in handlers.items():
            if host not in url:
                continue
            if handler is None:
                raise AssertionError(f"provider must not be called: {url}")
            if isinstance(handler, BaseException):
                raise handler
            return handler(url, kwargs) if callable(handler) else handler
        raise AssertionError(f"unstubbed URL: {url}")

    session = MagicMock()
    session.get.side_effect = get
    return session, calls
