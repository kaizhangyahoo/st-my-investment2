import re
from typing import List, Dict, Any, Optional, Tuple
from backend.app.core.config import settings
from backend.app.core.cache import MISS, cache
from backend.app.core.tracing import record_cache_hit, record_cache_miss, span

# Yahoo's suffix for each exchange Trading 212 lists on. Yahoo is what every chart in this app
# reads from (`market_service.get_ohlc`), and it keys on exchange, so an instrument cannot be
# charted until it is placed. US venues take no suffix.
_YAHOO_SUFFIX_BY_EXCHANGE = {
    "NASDAQ": "",
    "NYSE": "",
    "OTC Markets": "",
    "London Stock Exchange": ".L",
    "London Stock Exchange AIM": ".L",
    "London Stock Exchange NON-ISA": ".L",
    "Deutsche Börse Xetra": ".DE",
    "Gettex": ".DE",
    "Euronext Paris": ".PA",
    "Euronext Amsterdam": ".AS",
    "Euronext Brussels": ".BR",
    "Euronext Lisbon": ".LS",
    "Borsa Italiana": ".MI",
    "Bolsa de Madrid": ".MC",
    "SIX Swiss Exchange": ".SW",
    "Wiener Börse": ".VI",
    "Toronto Stock Exchange": ".TO",
}

# Platform metadata, identical for every account, so it is cached under a fixed key rather than
# through `ttl_cache` -- that decorator builds its key from `str(args)`, which would put the API
# key and secret into a process-wide dict. A day, because 18.5k instruments is a slow payload and
# a listing does not change intraday.
_SYMBOL_TTL = 86400
_SYMBOL_KEY = ("t212_chart_symbols",)

# Each history page costs one of 6 requests/minute, so the panel shows a recent window and says
# so rather than stalling the response until the whole account is paged in.
_HISTORY_PAGE = 50
_HISTORY_MAX_PAGES = 5


def get_t212_client(api_key: Optional[str] = None, api_secret: Optional[str] = None):
    key = api_key or settings.T212_API_KEY
    secret = api_secret or settings.T212_API_SECRET
    if not key or not secret:
        raise ValueError("Trading 212 API key and secret are required")
    from shared_service.trading212_api import Trading212API
    return Trading212API(api_key=key, api_secret=secret)

def fetch_t212_summary(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> Dict[str, Any]:
    client = get_t212_client(api_key, api_secret)
    summary = client.get_account_summary()
    cash = summary.get("cash") or {}
    inv = summary.get("investments") or {}
    return {
        "id": str(summary.get("id") or "N/A"),
        "currency": str(summary.get("currency") or "GBP"),
        "total_value": float(summary.get("totalValue") or 0.0),
        "cash_available": float(cash.get("availableToTrade") or 0.0),
        "investments_value": float(inv.get("currentValue") or 0.0),
        "unrealized_pnl": float(inv.get("unrealizedProfitLoss") or 0.0),
        "total_cost": float(inv.get("totalCost") or 0.0),
        "realized_pnl": float(inv.get("realizedProfitLoss") or 0.0)
    }

def _opt_float(value: Any) -> Optional[float]:
    """Float, or None when the field is genuinely absent.

    `float(x or 0.0)` is wrong for order history: a rejected order has no fill at all, and
    reporting its price as 0.00 reads as an execution at zero rather than as "never executed".
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _chart_symbols(client) -> Dict[str, str]:
    """`{t212_ticker: yahoo_symbol}` for every instrument that can be placed on an exchange.

    Two lookups are unavoidable. `shortName` is the exchange symbol, which the platform ticker
    does not reliably contain -- `ALCC1_US_EQ` is `OKLO`, keeping the pre-merger identity -- and
    `workingScheduleId` is the only link to the exchange, since the ticker suffix does not carry
    it either (`CNX1_EQ` is LSE-listed, `COPAl_EQ` quotes in USD). Deriving a symbol by slicing
    the ticker would therefore chart the wrong company.

    An instrument on an exchange Yahoo does not cover is simply absent, which the caller reports
    as "not chartable" rather than guessing a symbol that resolves to something else.
    """
    # The span covers the cache check as well as the build, and sits inside the function rather
    # than at each of its three call sites, so a hit is attributable wherever it is reached.
    with span("t212.instruments") as active:
        cached = cache.get(_SYMBOL_KEY, MISS)
        if cached is not MISS:
            record_cache_hit("t212_instruments")
            active.set_attribute("t212.instruments", len(cached))
            return cached
        # A miss costs two calls out of 6 requests/minute against an 18.5k-instrument payload,
        # which is why it is counted rather than merely implied by the span's duration.
        record_cache_miss("t212_instruments")

        exchange_by_schedule: Dict[int, str] = {}
        for exchange in client.get_exchanges() or []:
            name = str(exchange.get("name") or "")
            for schedule in exchange.get("workingSchedules") or []:
                if schedule.get("id") is not None:
                    exchange_by_schedule[int(schedule["id"])] = name

        symbols: Dict[str, str] = {}
        for inst in client.get_instruments() or []:
            ticker, short = inst.get("ticker"), inst.get("shortName")
            schedule = inst.get("workingScheduleId")
            if not ticker or not short or schedule is None:
                continue
            suffix = _YAHOO_SUFFIX_BY_EXCHANGE.get(exchange_by_schedule.get(int(schedule), ""))
            if suffix is None:
                continue
            symbols[str(ticker)] = f"{short}{suffix}"

        cache.set(_SYMBOL_KEY, symbols, ttl=_SYMBOL_TTL)
        active.set_attribute("t212.instruments", len(symbols))
        active.set_attribute("t212.exchanges", len(exchange_by_schedule))
        return symbols


def _paginate(fetch, max_pages: int, operation: str) -> Tuple[List[Dict[str, Any]], bool]:
    """Walk `nextPagePath` up to `max_pages`, reporting whether anything was left behind.

    `operation` names the span, because `fetch` is an opaque lambda that cannot name itself. Two
    literal values, so the span name stays bounded.
    """
    with span(f"t212.{operation}", **{"t212.max_pages": max_pages}) as active:
        items, truncated, pages = _walk_pages(fetch, max_pages)
        active.set_attribute("t212.pages", pages)
        active.set_attribute("t212.items", len(items))
        # Nothing records this today, and it is the whole reason the panel shows a window rather
        # than the account: each page costs one of 6 requests/minute.
        active.set_attribute("t212.truncated", truncated)
        return items, truncated


def _walk_pages(fetch, max_pages: int) -> Tuple[List[Dict[str, Any]], bool, int]:
    """The walk itself, plus how many pages it fetched. Split out because its three in-loop
    returns leave nowhere to set the attributes once; the cursor is read back out of
    `nextPagePath` because that is the only place the API publishes it, and the `cursor` query
    parameter it names is what the client accepts.
    """
    items: List[Dict[str, Any]] = []
    cursor: Optional[int] = None
    pages = 0
    for _ in range(max_pages):
        page = fetch(cursor) or {}
        pages += 1
        items.extend(page.get("items") or [])
        next_path = page.get("nextPagePath")
        if not next_path:
            return items, False, pages
        match = re.search(r"cursor=(\d+)", str(next_path))
        if not match:
            return items, True, pages
        cursor = int(match.group(1))
    return items, True, pages


def _fill_fees(wallet: Dict[str, Any]) -> Optional[float]:
    """Total charged on a fill, in the wallet's own currency. Already signed negative.

    Restricted to taxes quoted in the wallet currency because each tax carries its own, and
    adding a USD charge to a GBP one would produce a number in neither. Live data has only ever
    used the wallet currency, so in practice this sums everything.
    """
    if not wallet:
        return None
    currency = wallet.get("currency")
    return float(sum(
        float(t.get("quantity") or 0.0)
        for t in (wallet.get("taxes") or [])
        if t.get("currency") == currency
    ))


def fetch_t212_orders(
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    max_pages: int = _HISTORY_MAX_PAGES,
) -> Dict[str, Any]:
    """Recent order history, newest first, with the execution detail each order actually has.

    One entry per *fill*, not per order: a 68-share order in this account came back as 23 tranches
    at prices from 154.14 to 154.18, whose quantities sum to exactly 68. So `id` repeats across
    rows and only `fill_id` identifies one, which is why both are returned.

    Most orders never filled at all -- 34 of the first 50 here were REJECTED or CANCELLED -- and
    those carry no `fill` object. Every field sourced from the fill is therefore nullable, so the
    blotter can show a rejected order as a rejected order instead of inventing a £0.00 execution.
    """
    client = get_t212_client(api_key, api_secret)
    symbols = _chart_symbols(client)
    raw, truncated = _paginate(
        lambda cursor: client.get_historical_orders(cursor=cursor, limit=_HISTORY_PAGE),
        max_pages,
        operation="orders_history",
    )

    orders = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        order = entry.get("order") or {}
        fill = entry.get("fill") or {}
        wallet = fill.get("walletImpact") or {}
        inst = order.get("instrument") or {}
        ticker = str(order.get("ticker") or inst.get("ticker") or "")
        fill_id = fill.get("id")
        orders.append({
            "id": str(order.get("id") or ""),
            "fill_id": None if fill_id is None else str(fill_id),
            "created_at": order.get("createdAt"),
            "filled_at": fill.get("filledAt"),
            "ticker": ticker,
            "symbol": symbols.get(ticker),
            "name": str(inst.get("name") or ticker),
            "side": str(order.get("side") or ""),
            "type": str(order.get("type") or ""),
            "status": str(order.get("status") or ""),
            "quantity": _opt_float(order.get("quantity")),
            # `or` would be wrong here: a partial cancel reports a real 0.0 and must keep it.
            "filled_quantity": _opt_float(
                order.get("filledQuantity") if fill.get("quantity") is None
                else fill.get("quantity")
            ),
            "fill_price": _opt_float(fill.get("price")),
            "fill_type": fill.get("type"),
            "currency": str(inst.get("currency") or ""),
            "fees": _fill_fees(wallet),
            "net_value": _opt_float(wallet.get("netValue")),
            "net_currency": wallet.get("currency"),
            "fx_rate": _opt_float(wallet.get("fxRate")),
        })
    return {"items": orders, "truncated": truncated}


def fetch_t212_dividends(
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    max_pages: int = _HISTORY_MAX_PAGES,
) -> Dict[str, Any]:
    """Dividends actually paid out, as the API reports them.

    Withholding tax and tax regime are deliberately absent: the endpoint returns neither, and
    there is no rate in the response to derive them from. `amount` is net in the account
    currency while `grossAmountPerShare` is in the instrument's, so the gap between them is
    WHT *and* FX together and cannot be split into the two.
    """
    client = get_t212_client(api_key, api_secret)
    symbols = _chart_symbols(client)
    raw, truncated = _paginate(
        lambda cursor: client.get_dividends(cursor=cursor, limit=_HISTORY_PAGE),
        max_pages,
        operation="dividends_history",
    )

    dividends = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        inst = entry.get("instrument") or {}
        ticker = str(entry.get("ticker") or inst.get("ticker") or "")
        dividends.append({
            "paid_on": entry.get("paidOn"),
            "ticker": ticker,
            "symbol": symbols.get(ticker),
            "name": str(inst.get("name") or ticker),
            "quantity": float(entry.get("quantity") or 0.0),
            "gross_per_share": float(entry.get("grossAmountPerShare") or 0.0),
            "instrument_currency": str(inst.get("currency") or ""),
            "amount": float(entry.get("amount") or 0.0),
            "currency": str(entry.get("currency") or ""),
            "type": str(entry.get("type") or ""),
        })
    return {"items": dividends, "truncated": truncated}


def fetch_t212_positions(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_t212_client(api_key, api_secret)
    positions_raw = client.get_open_positions()
    # Carried on the position so the instrument inspector can chart it. The platform ticker is
    # not a market symbol, and the index is cached for a day, so this is one lookup per process.
    symbols = _chart_symbols(client)


    if isinstance(positions_raw, dict):
        if "items" in positions_raw:
            positions_raw = positions_raw["items"]
        elif "errorMessage" in positions_raw or "code" in positions_raw:
            raise ValueError(f"Trading 212 API error: {positions_raw.get('errorMessage') or positions_raw.get('code')}")
        else:
            positions_raw = []
    elif not isinstance(positions_raw, list):
        positions_raw = []

    positions = []
    for pos in positions_raw:
        if not isinstance(pos, dict):
            continue
        inst = pos.get("instrument") or {}
        wallet = pos.get("walletImpact") or {}
        ticker = str(inst.get("ticker") or pos.get("ticker") or "")
        positions.append({
            "ticker": ticker,
            "symbol": symbols.get(ticker),
            "name": str(inst.get("name") or pos.get("name") or ""),
            "isin": str(inst.get("isin") or pos.get("isin") or ""),
            "currency": str(inst.get("currency") or pos.get("currency") or "GBP"),
            "quantity": float(pos.get("quantity") or 0.0),
            "avg_price_paid": float(pos.get("averagePricePaid") or 0.0),
            "current_price": float(pos.get("currentPrice") or 0.0),
            "total_cost_gbp": float(wallet.get("totalCost") or 0.0),
            "current_value_gbp": float(wallet.get("currentValue") or 0.0),
            "unrealized_pnl_gbp": float(wallet.get("unrealizedProfitLoss") or 0.0),
            "fx_impact_gbp": float(wallet.get("fxImpact") or 0.0)
        })
    return positions
