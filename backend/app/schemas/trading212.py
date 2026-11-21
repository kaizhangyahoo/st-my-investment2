from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class T212AccountSummary(BaseModel):
    id: str
    currency: str
    total_value: float
    cash_available: float
    investments_value: float
    unrealized_pnl: float
    total_cost: float
    realized_pnl: float

class T212Position(BaseModel):
    ticker: str
    symbol: Optional[str] = None  # exchange symbol for charting; absent if not on a Yahoo venue
    name: str
    isin: str
    currency: str
    quantity: float
    avg_price_paid: float
    current_price: float
    total_cost_gbp: float
    current_value_gbp: float
    unrealized_pnl_gbp: float
    fx_impact_gbp: float

class T212Order(BaseModel):
    """One row of history, which is one *fill* rather than one order: a 68-share order here came
    back as 23 tranches, so `id` repeats and `fill_id` is what identifies a row.

    Everything the fill supplies is optional because most orders in a real account never fill --
    34 of the first 50 here were REJECTED or CANCELLED and carry no fill object -- and a null
    price is the honest way to say "no execution"."""
    id: str
    fill_id: Optional[str] = None
    created_at: Optional[str] = None
    filled_at: Optional[str] = None
    ticker: str
    symbol: Optional[str] = None  # exchange symbol for charting; absent if not on a Yahoo venue
    name: str
    side: str
    type: str
    status: str
    quantity: Optional[float] = None
    filled_quantity: Optional[float] = None
    fill_price: Optional[float] = None
    fill_type: Optional[str] = None
    currency: str
    fees: Optional[float] = None
    net_value: Optional[float] = None
    net_currency: Optional[str] = None
    fx_rate: Optional[float] = None

class T212Dividend(BaseModel):
    """One dividend payment. No withholding-tax or tax-regime field: the API returns neither, and
    `amount` (net, account currency) minus gross (instrument currency) is WHT and FX combined."""
    paid_on: Optional[str] = None
    ticker: str
    symbol: Optional[str] = None
    name: str
    quantity: float
    gross_per_share: float
    instrument_currency: str
    amount: float
    currency: str
    type: str

class T212OrderPage(BaseModel):
    """`truncated` is the panel's licence to say so: history is 6 req/min, so only a recent
    window is paged in rather than stalling the response on the whole account."""
    items: List[T212Order]
    truncated: bool = False

class T212DividendPage(BaseModel):
    items: List[T212Dividend]
    truncated: bool = False

