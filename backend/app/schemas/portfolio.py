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

class CashBalance(BaseModel):
    """Settled cash implied by the transaction statement, plus the window it was derived from.

    Not a broker figure -- IG's "available to trade" nets margin and unsettled trades, and this
    repo has no IG balance client. `balance_gbp` is null whenever the statement cannot support a
    balance, and `withheld_reason` names the check that failed; a partial export nets to a
    plausible-looking wrong number, so withholding beats approximating.
    """
    balance_gbp: Optional[float] = None
    covered_from: Optional[str] = None
    covered_to: Optional[str] = None
    withheld_reason: Optional[str] = None

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
    # `total_invested_cash` above is cost basis, not cash. This is the uninvested balance.
    cash_balance: Optional[CashBalance] = None

class PortfolioHistoryPoint(BaseModel):
    date: str
    value: float

class UnconvertibleHolding(BaseModel):
    ticker: str
    currency: str

class HistoryDataQuality(BaseModel):
    """Why the series may be incomplete. `skipped_dates` counts trading days dropped because an
    open position had no close that day -- the series is sparse there, not flat.
    `fx_unbacked_dates` counts the ones dropped instead because a non-GBP position would have
    been converted at a rate no provider quoted; those are withheld rather than persisted, since
    the shared values file cannot record that a figure was approximated."""
    degraded: bool = False
    fx_fallback: bool = False
    skipped_dates: int = 0
    fx_unbacked_dates: int = 0
    unpriced_tickers: List[str] = []
    unconvertible: List[UnconvertibleHolding] = []

class PortfolioHistoryResponse(BaseModel):
    points: List[PortfolioHistoryPoint]
    computed_at: str
    data_quality: HistoryDataQuality
    # Account keys stored in user_portfolio_values.json; `account_id` is the one returned.
    accounts: List[str] = []
    account_id: Optional[str] = None
    # Whether recomputing could add dates to this account, i.e. whether to offer it at all.
    fillable_gap: bool = False

class RiskMetrics(BaseModel):
    """One timeframe's statistics. Every optional field is null when the window cannot support
    it, and the client renders a null as "unavailable" rather than as a zero."""
    timeframe: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    trading_days: int = 0
    cumulative_return_pct: Optional[float] = None
    cumulative_return_gbp: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    annualised_volatility_pct: Optional[float] = None
    # Never populated yet: there is no GBP risk-free rate source, and an excess return computed
    # against an assumed one would be a figure no fetched data backs.
    sharpe_ratio: Optional[float] = None

class RealisedMetrics(BaseModel):
    """One timeframe's closed-trade result (KAN-52).

    Separate from `RiskMetrics` because it comes from the trade statement rather than the stored
    value series, and the two end on different dates. `start_date`/`end_date` are the bounds the
    disposals actually span, so the tile states its own period instead of the curve's."""
    timeframe: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    disposals: int = 0
    winning_disposals: int = 0
    win_rate_pct: Optional[float] = None
    realised_pnl_gbp: Optional[float] = None

class RealisedCoverage(BaseModel):
    """What the realised figures were computed from, and what they had to leave out.

    `excluded_tickers` are holdings whose cost basis is not derivable from this statement -- free
    stock from a spin-off with no parent leg -- so their disposals are omitted rather than booked
    against zero. `corporate_action_cash_gbp` is cash from fractional entitlements, which is real
    money but not a disposal, so it sits beside the P&L rather than inside it."""
    source_file: Optional[str] = None
    corporate_action_rows: int = 0
    corporate_action_cash_gbp: float = 0.0
    excluded_disposals: int = 0
    excluded_tickers: List[str] = []
    # Set when no statement is loaded. The client must render a dash, not a 0% win rate.
    unavailable_reason: Optional[str] = None

class PortfolioMetricsResponse(BaseModel):
    account_id: Optional[str] = None
    # Keyed by timeframe, so the client can switch windows without another request.
    windows: Dict[str, RiskMetrics] = {}
    # Closed-trade results per timeframe, same keys as `windows`.
    realised: Dict[str, RealisedMetrics] = {}
    realised_coverage: Optional[RealisedCoverage] = None

class BenchmarkPoint(BaseModel):
    date: str
    value: float

class BenchmarkResponse(BaseModel):
    symbol: str
    currency: Optional[str] = None
    # Raw closes in the symbol's own quote currency. The client rebases them onto the
    # portfolio's first visible value, which cancels the unit, so a GBp quote needs no
    # conversion here -- unlike a valuation, where the pence/pounds distinction matters.
    points: List[BenchmarkPoint] = []
    # Set when the provider returned nothing. The client must draw no line at all in that case.
    unavailable_reason: Optional[str] = None

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
    # False merges into the stored map; True makes the payload the whole map.
    replace: bool = False

