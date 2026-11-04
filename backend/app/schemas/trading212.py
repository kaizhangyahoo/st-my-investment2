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
    date: Optional[str] = None
    side: str
    type: str
    ticker: str
    name: str
    quantity: float
    price: float
    currency: str
    net_value_gbp: float

class T212Dividend(BaseModel):
    paid_on: str
    ticker: str
    name: str
    amount_gbp: float
    quantity: float
    gross_per_share: float
    type: str

