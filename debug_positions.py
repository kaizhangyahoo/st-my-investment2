import pandas as pd
from trading212_api import Trading212API 
from trading212.t212dec import lss
import time
from urllib.parse import urlparse, parse_qs

# this script is for debugging the positions calcuation
# It fetches all historical orders, aggregates them by order and by fills
# It also fetches all open positions and compares the cumulative sum of filled orders
# then investigate the discrepancies between the two datasets to identify potential issues in the positions calculation logic.

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
if api_key is None or api_secret is None:
    raise ValueError("Failed to retrieve API credentials. Please check your passcode and t212.dat file.")
t212 = Trading212API(api_key, api_secret)
positions_raw = t212.get_open_positions()

df_positions = pd.DataFrame(positions_raw)
print("get_open_positions function queries an api that spit out the latest positions snapshot.")
print(df_positions[['instrument', 'quantity']])



# calculate positions from historical orders and fills


# The logic is to fetch all historical orders, then aggregate them by fills
all_orders = fetch_all_paginated(t212.get_historical_orders, label="all orders", delay=10.0)
order_aggregates = {}
seen_fill_ids = set()  

for item in all_orders:
    order = item.get("order", {})
    if order.get("status") != "FILLED":
        continue
    order_id = order.get("id")
    fill = item.get("fill", {})

    fill_id = fill.get("id")
    if fill_id and fill_id in seen_fill_ids:
        continue # skip duplicate fills
    if fill_id:
        seen_fill_ids.add(fill_id)


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

df_fill_positions = df_daily_trades.cumsum()

# Expand to every calendar day up to today, forward-filling positions
today = pd.Timestamp.now(tz='UTC').normalize()
full_date_range = pd.date_range(start=df_fill_positions.index.min(), end=today, freq='D')
df_fill_positions = df_fill_positions.reindex(full_date_range).ffill().fillna(0)
df_fill_positions.index.name = 'Date'

print(df_fill_positions.tail(5))

# the logic below is to aggregate orders
records = []
for item in all_orders:
    order = item['order']
    if order.get('status') == 'FILLED':
        records.append({
            'id':             order['id'],
            'type':           order['type'],
            'ticker':         order['ticker'],
            'quantity':       order.get('quantity'),          # None for VALUE strategy orders
            'filledQuantity': order.get('filledQuantity'),    # None for VALUE strategy orders
            'price':          order.get('limitPrice'),        # None for MARKET orders
            'status':         order['status'],
            'currency':       order['currency'],
            'side':           order['side'],
            'createdAt':      pd.to_datetime(order['createdAt']).date(),
        })

df_all_orders = pd.DataFrame(records).drop_duplicates(subset='id').reset_index(drop=True)
df_order_positions = df_all_orders.pivot_table(index='ticker', values='filledQuantity', aggfunc='sum')
print(df_order_positions)
 