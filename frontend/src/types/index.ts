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

export interface PortfolioSummary {
  total_market_value_gbp: number;
  total_invested_cash: number;
  total_pnl_gbp: number;
  currency_allocation: CurrencyAllocation;
  positions: Position[];
}

export interface PortfolioHistoryPoint {
  date: string;
  value: number;
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

