import pandas as pd
from trading212_api import Trading212API 
from trading212.t212dec import lss
import time
from urllib.parse import urlparse, parse_qs


def fetch_all_paginated(api_func, label="data", delay=1.0, **kwargs):
    """Fetch all items from a paginated Trading 212 API endpoint."""
    all_items = []
    cursor = None
    page = 1
    while True:
        print(f"Fetching {label}... (Page {page}, {len(all_items)} items so far)")    
        if cursor is not None:
            result = api_func(cursor=cursor, limit=50, **kwargs)
        else:
            result = api_func(limit=50, **kwargs)

        items = result.get("items", [])
        all_items.extend(items)
        next_page = result.get("nextPagePath")
     
        if not next_page or not items:
            break          

        # Extract cursor from nextPagePath query params
        parsed = parse_qs(urlparse(next_page).query)
        cursor = parsed.get("cursor", [None])[0]
        page += 1

    
        # Respect rate limits
        if delay > 0:
            time.sleep(delay)
    return all_items

api_key, api_secret = lss("63246807")

t212 = Trading212API(api_key, api_secret)
positions_raw = t212.get_open_positions()

df_positions = pd.DataFrame(positions_raw)

print(df_positions)

all_orders = fetch_all_paginated(t212.get_historical_orders, label="all orders", delay=10.0)
order_aggregates = {}
for item in all_orders:
    order = item.get("order", {})
    if order.get("status") != "FILLED":
        continue
    order_id = order.get("id")
    fill = item.get("fill", {})
    instrument = order.get("instrument", {})
    side = order.get("side", "")
    qty = fill.get("quantity", order.get("filledQuantity", order.get("quantity", 0)))
    
    if order_id not in order_aggregates:
        order_aggregates[order_id] = {
            "Date": pd.to_datetime(fill.get("filledAt", order.get("createdAt", "")), utc=True, errors="coerce"),
            "Ticker_T212": order.get("ticker", ""),
            "Currency": instrument.get("currency", order.get("currency", "")),
            "Quantity": 0,
            "Price": fill.get("price", 0),
            "Side": side,
        }
    order_aggregates[order_id]["Quantity"] += qty
    if fill.get("price"):
        order_aggregates[order_id]["Price"] = fill.get("price", 0)

trade_rows = []
for order_id, data in order_aggregates.items():
    signed_qty = data["Quantity"] if data["Side"] == "BUY" else -data["Quantity"]
    trade_rows.append({
        "Date": data["Date"],
        "Ticker_T212": data["Ticker_T212"],
        "Currency": data["Currency"],
        "Signed_Qty": signed_qty,
        "Price": data["Price"],
    })
df_all_trades = pd.DataFrame(trade_rows)

df_all_trades.sort_values("Date", inplace=True)
df_all_trades['Date'] = df_all_trades['Date'].dt.normalize() 
df_daily_trades = df_all_trades.pivot_table(
    index='Date', 
    columns='Ticker_T212',
    values='Signed_Qty', 
    aggfunc='sum'
).fillna(0)

df_positions = df_daily_trades.cumsum()

# print last row of df_positions

print(df_positions.iloc[-1])