from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class Position(BaseModel):
    ticker: str
    market: str
    quantity: float
    current_price: Optional[float] = None
    market_value_gbp: float
    pnl_gbp: float
    currency: str

class CurrencyAllocation(BaseModel):
    usd_gbp: float
    eur_gbp: float
    gbp: float
    total_gbp: float

class PortfolioSummary(BaseModel):
    total_market_value_gbp: float
    total_invested_cash: float
    total_pnl_gbp: float
    currency_allocation: CurrencyAllocation
    positions: List[Position]

class PortfolioHistoryPoint(BaseModel):
    date: str
    value: float

class BenchmarkPoint(BaseModel):
    date: str
    value: float

class CashflowItem(BaseModel):
    category: str
    amount: float

class TickerMappingItem(BaseModel):
    market_name: str
    ticker: Optional[str] = None
    include: bool = True

class ResolveTickersRequest(BaseModel):
    market_names: List[str]

class UpdateMappingsRequest(BaseModel):
    mappings: Dict[str, str]

