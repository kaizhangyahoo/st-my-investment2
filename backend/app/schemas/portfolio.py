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

class TradeActivityItem(BaseModel):
    qty: float
    fill: str
    value: str
    date: str
    time: str
    activity: str
    market: str
    ticker: Optional[str] = None

class UnresolvedSymbol(BaseModel):
    market_name: str
    row_count: int

class ProviderFailure(BaseModel):
    ticker: str
    provider: str
    reason: str

class DataQuality(BaseModel):
    """Why the figures may be wrong. `failures` records every provider attempt that yielded no
    price, so a ticker can appear there and still be priced — that means a fallback worked."""
    degraded: bool = False
    fx_fallback: bool = False
    unpriced_tickers: List[str] = []
    failures: List[ProviderFailure] = []

class PortfolioSummary(BaseModel):
    total_market_value_gbp: float
    total_invested_cash: float
    total_pnl_gbp: float
    currency_allocation: CurrencyAllocation
    positions: List[Position]
    source_file: Optional[str] = None
    transaction_file: Optional[str] = None
    trade_activities: Optional[List[TradeActivityItem]] = None
    missing_trade_history: bool = False
    unresolved_symbols: List[UnresolvedSymbol] = []
    excluded_row_count: int = 0
    data_quality: Optional[DataQuality] = None

class PortfolioHistoryPoint(BaseModel):
    date: str
    value: float

class UnconvertibleHolding(BaseModel):
    ticker: str
    currency: str

class HistoryDataQuality(BaseModel):
    """Why the series may be incomplete. `skipped_dates` counts trading days dropped because an
    open position had no close that day -- the series is sparse there, not flat."""
    degraded: bool = False
    fx_fallback: bool = False
    skipped_dates: int = 0
    unpriced_tickers: List[str] = []
    unconvertible: List[UnconvertibleHolding] = []

class PortfolioHistoryResponse(BaseModel):
    points: List[PortfolioHistoryPoint]
    computed_at: str
    data_quality: HistoryDataQuality
    # Account keys stored in user_portfolio_values.json; `account_id` is None for the total.
    accounts: List[str] = []
    account_id: Optional[str] = None

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

