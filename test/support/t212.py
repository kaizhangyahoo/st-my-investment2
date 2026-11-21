"""A stand-in for `Trading212API`, built from real response shapes.

Everything here was copied from what the live account actually returns, because the mock data
this replaced in the UI had been written from the ticker column alone and was not reachable from
the API: it used `TRI` and `EQQQ.L` where the platform reports `TRI_US_EQ`, and it gave every
order a fill. Tests built on guessed shapes would have passed against the same fiction.
"""
from typing import Any, Dict, List, Optional

# Two working schedules on one exchange, which is how T212 actually lists LSE.
EXCHANGES = [
    {"id": 1, "name": "NASDAQ", "workingSchedules": [{"id": 71}]},
    {"id": 2, "name": "London Stock Exchange", "workingSchedules": [{"id": 70}, {"id": 154}]},
    {"id": 3, "name": "Bucharest Stock Exchange", "workingSchedules": [{"id": 99}]},
]

# `ALCC1_US_EQ`/`OKLO` is the case that rules out deriving a symbol from the ticker: the platform
# id keeps the pre-merger SPAC identity. `CNX1_EQ` is the other half -- LSE-listed with nothing in
# the ticker to say so.
INSTRUMENTS = [
    {"ticker": "GOOG_US_EQ", "shortName": "GOOG", "name": "Alphabet (Class C)",
     "currencyCode": "USD", "workingScheduleId": 71},
    {"ticker": "ALCC1_US_EQ", "shortName": "OKLO", "name": "Oklo",
     "currencyCode": "USD", "workingScheduleId": 71},
    {"ticker": "CNX1_EQ", "shortName": "CNX1", "name": "iShares NASDAQ 100",
     "currencyCode": "GBX", "workingScheduleId": 154},
    {"ticker": "TVBETNG_EQ", "shortName": "TVBETNG", "name": "Bucharest listing",
     "currencyCode": "RON", "workingScheduleId": 99},
    {"ticker": "BROKEN_EQ", "shortName": "BROKEN", "name": "No schedule", "currencyCode": "USD"},
]


def filled_order(
    order_id: str = "59307261023",
    ticker: str = "GOOG_US_EQ",
    side: str = "BUY",
    taxes: Optional[List[Dict[str, Any]]] = None,
    fill_id: str = "59307261024",
    fill_price: float = 316.77,
    fill_quantity: float = 3.0,
) -> Dict[str, Any]:
    return {
        "order": {
            "id": order_id,
            "createdAt": "2026-10-23T13:42:47.000Z",
            "ticker": ticker,
            "side": side,
            "type": "LIMIT",
            "status": "FILLED",
            "quantity": 3.0,
            "instrument": {"ticker": ticker, "name": "Alphabet (Class C)",
                           "currency": "USD", "isin": "US02079K1079"},
        },
        "fill": {
            "id": fill_id,
            "filledAt": "2026-10-26T13:31:06.000Z",
            "price": fill_price,
            "quantity": fill_quantity,
            "type": "TRADE",
            "walletImpact": {
                "currency": "GBP",
                "fxRate": 1.3341991,
                "netValue": 713.34,
                "realisedProfitLoss": 0.0,
                "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "currency": "GBP",
                           "quantity": -1.07, "chargedAt": "2026-10-26T13:31:06.000Z"}]
                if taxes is None else taxes,
            },
        },
    }


def rejected_order(order_id: str = "59258603081", ticker: str = "GOOG_US_EQ") -> Dict[str, Any]:
    """No `fill` key at all -- 34 of the first 50 live orders look exactly like this."""
    return {
        "order": {
            "id": order_id,
            "createdAt": "2026-01-22T16:00:25.000Z",
            "ticker": ticker,
            "side": "BUY",
            "type": "LIMIT",
            "status": "REJECTED",
            "quantity": 3.0,
            "filledQuantity": 0.0,
            "instrument": {"ticker": ticker, "name": "Alphabet (Class C)",
                           "currency": "USD", "isin": "US02079K1079"},
        }
    }


def dividend(ticker: str = "GOOG_US_EQ", amount: float = 1.38,
             div_type: str = "DIVIDEND") -> Dict[str, Any]:
    return {
        "paidOn": "2026-09-14T14:01:44.000+03:00",
        "ticker": ticker,
        "quantity": 10.0,
        "grossAmountPerShare": 0.22,
        "amount": amount,
        "currency": "GBP",
        "type": div_type,
        "instrument": {"ticker": ticker, "name": "Alphabet (Class C)", "currency": "USD"},
    }


POSITION = {
    "ticker": "GOOG_US_EQ",
    "quantity": 13.0,
    "averagePricePaid": 290.11,
    "currentPrice": 316.77,
    "instrument": {"ticker": "GOOG_US_EQ", "name": "Alphabet (Class C)",
                   "currency": "USD", "isin": "US02079K1079"},
    "walletImpact": {"totalCost": 2825.0, "currentValue": 3086.0,
                     "unrealizedProfitLoss": 261.0, "fxImpact": -12.0},
}


class FakeT212Client:
    """Records every call, so a test can assert what was *not* asked for.

    Pages are served as given: a page carrying `nextPagePath` is how the API advertises more
    data, and the cursor has to be parsed back out of that path because it is published nowhere
    else.
    """

    def __init__(self, order_pages=None, dividend_pages=None, positions=None,
                 instruments=None, exchanges=None):
        self.order_pages = order_pages if order_pages is not None else [{"items": []}]
        self.dividend_pages = dividend_pages if dividend_pages is not None else [{"items": []}]
        self.positions = positions if positions is not None else []
        self.instruments = INSTRUMENTS if instruments is None else instruments
        self.exchanges = EXCHANGES if exchanges is None else exchanges
        self.calls: List[str] = []

    def _page(self, pages, cursor):
        index = 0 if cursor is None else next(
            (i for i, p in enumerate(pages) if p.get("_cursor") == cursor), 0
        )
        return pages[index] if index < len(pages) else {"items": []}

    def get_historical_orders(self, cursor=None, ticker=None, limit=20):
        self.calls.append(f"orders:{cursor}")
        return self._page(self.order_pages, cursor)

    def get_dividends(self, cursor=None, ticker=None, limit=20):
        self.calls.append(f"dividends:{cursor}")
        return self._page(self.dividend_pages, cursor)

    def get_open_positions(self, ticker=None):
        self.calls.append("positions")
        return self.positions

    def get_instruments(self):
        self.calls.append("instruments")
        return self.instruments

    def get_exchanges(self):
        self.calls.append("exchanges")
        return self.exchanges


def page(items, next_cursor=None, cursor=None):
    """One history page. `next_cursor` makes it advertise a successor."""
    built: Dict[str, Any] = {"items": items}
    if cursor is not None:
        built["_cursor"] = cursor
    if next_cursor is not None:
        built["nextPagePath"] = f"/api/v0/equity/history/orders?cursor={next_cursor}&limit=50"
    return built
