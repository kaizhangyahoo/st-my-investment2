export interface UserProfile {
  email: string;
  name?: string;
  provider: string;
  user_id?: string;
}

export interface Position {
  ticker: string;
  market: string;
  quantity: number;
  current_price?: number;
  market_value_gbp: number;
  pnl_gbp: number;
  currency: string;
}

export interface CurrencyAllocation {
  usd_gbp: number;
  eur_gbp: number;
  gbp: number;
  total_gbp: number;
}

export interface TradeActivityItem {
  qty: number;
  fill: string;
  value: string;
  date: string;
  time: string;
  activity: string;
  market: string;
  ticker?: string | null;
}

export interface UnresolvedSymbol {
  market_name: string;
  row_count: number;
}

export interface ProviderFailure {
  ticker: string;
  provider: string;
  reason: string;
}

/** A ticker can appear in `failures` and still be priced — that means a fallback worked. */
export interface DataQuality {
  degraded: boolean;
  fx_fallback: boolean;
  unpriced_tickers: string[];
  failures: ProviderFailure[];
}

export interface PortfolioSummary {
  total_market_value_gbp: number;
  total_invested_cash: number;
  total_pnl_gbp: number;
  currency_allocation: CurrencyAllocation;
  positions: Position[];
  source_file?: string | null;
  transaction_file?: string | null;
  trade_activities?: TradeActivityItem[];
  missing_trade_history?: boolean;
  unresolved_symbols?: UnresolvedSymbol[];
  excluded_row_count?: number;
  data_quality?: DataQuality | null;
}

export type FeedState = 'loading' | 'live' | 'partial' | 'degraded' | 'offline';

export interface FeedStatus {
  state: FeedState;
  detail: string[];
}

export interface UploadResult {
  trade_files: string[];
  transaction_files: string[];
  errors: string[];
  missing_trade_history: boolean;
  unresolved_symbols: UnresolvedSymbol[];
}

export interface PortfolioHistoryPoint {
  date: string;
  value: number;
}

export interface HistoryDataQuality {
  degraded: boolean;
  fx_fallback: boolean;
  // Trading days dropped because an open position had no close that day. The series is sparse
  // across those dates, not flat.
  skipped_dates: number;
  // Trading days dropped instead because a non-GBP position would have needed an FX rate no
  // provider quoted. Withheld rather than stored as an estimate.
  fx_unbacked_dates: number;
  unpriced_tickers: string[];
  unconvertible: { ticker: string; currency: string }[];
}

export interface PortfolioHistoryResponse {
  points: PortfolioHistoryPoint[];
  computed_at: string;
  data_quality: HistoryDataQuality;
  // Account keys stored in user_portfolio_values.json. account_id is the one this series is
  // for, resolved by the backend when the request omitted it.
  accounts: string[];
  account_id: string | null;
  // True only when recomputing this account could actually add dates to it.
  fillable_gap: boolean;
}

/** One timeframe's statistics. A null field means the window cannot support that figure —
 *  render it as unavailable, never as a zero, which reads as a real measurement. */
export interface RiskMetrics {
  timeframe: string;
  start_date: string | null;
  end_date: string | null;
  trading_days: number;
  cumulative_return_pct: number | null;
  cumulative_return_gbp: number | null;
  max_drawdown_pct: number | null;
  annualised_volatility_pct: number | null;
  // Always null: there is no GBP risk-free rate source, so an excess return would be assumed.
  sharpe_ratio: number | null;
}

export interface RealisedMetrics {
  timeframe: string;
  // The bounds the disposals actually span, which are not the value series' bounds.
  start_date: string | null;
  end_date: string | null;
  disposals: number;
  winning_disposals: number;
  // Null when the window closed nothing. Rendering that as 0% would read as "every trade lost".
  win_rate_pct: number | null;
  realised_pnl_gbp: number | null;
}

export interface RealisedCoverage {
  source_file: string | null;
  corporate_action_rows: number;
  // Cash from fractional entitlements: real money, but not a disposal, so it sits outside the P&L.
  corporate_action_cash_gbp: number;
  excluded_disposals: number;
  // Holdings whose cost basis is not in the statement, e.g. free stock from a spin-off.
  excluded_tickers: string[];
  // Set when no statement is loaded; show a dash, never a 0% win rate.
  unavailable_reason: string | null;
}

export interface PortfolioMetricsResponse {
  account_id: string | null;
  // Keyed by timeframe, so switching window costs no further request.
  windows: Record<string, RiskMetrics>;
  // Closed-trade results, same timeframe keys as `windows` but from the trade statement.
  realised: Record<string, RealisedMetrics>;
  realised_coverage: RealisedCoverage | null;
}

export interface BenchmarkResponse {
  symbol: string;
  currency: string | null;
  // Raw closes in the symbol's own quote currency, not portfolio units.
  points: { date: string; value: number }[];
  // Set when the provider returned nothing; draw no line at all in that case.
  unavailable_reason: string | null;
}

export interface CashflowItem {
  category: string;
  amount: number;
}

export interface T212AccountSummary {
  id: string;
  currency: string;
  total_value: number;
  cash_available: number;
  investments_value: number;
  unrealized_pnl: number;
  total_cost: number;
  realized_pnl: number;
}

export interface T212Position {
  ticker: string;
  name: string;
  isin: string;
  currency: string;
  quantity: number;
  avg_price_paid: number;
  current_price: number;
  total_cost_gbp: number;
  current_value_gbp: number;
  unrealized_pnl_gbp: number;
  fx_impact_gbp: number;
}

