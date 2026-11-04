from typing import List, Dict, Any, Optional
from backend.app.core.config import settings

def get_t212_client(api_key: Optional[str] = None, api_secret: Optional[str] = None):
    key = api_key or settings.T212_API_KEY
    secret = api_secret or settings.T212_API_SECRET
    if not key or not secret:
        raise ValueError("Trading 212 API key and secret are required")
    from trading212_api import Trading212API
    return Trading212API(api_key=key, api_secret=secret)

def fetch_t212_summary(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> Dict[str, Any]:
    client = get_t212_client(api_key, api_secret)
    summary = client.get_account_summary()
    cash = summary.get("cash", {})
    inv = summary.get("investments", {})
    return {
        "id": str(summary.get("id", "N/A")),
        "currency": str(summary.get("currency", "GBP")),
        "total_value": float(summary.get("totalValue", 0)),
        "cash_available": float(cash.get("availableToTrade", 0)),
        "investments_value": float(inv.get("currentValue", 0)),
        "unrealized_pnl": float(inv.get("unrealizedProfitLoss", 0)),
        "total_cost": float(inv.get("totalCost", 0)),
        "realized_pnl": float(inv.get("realizedProfitLoss", 0))
    }

def fetch_t212_positions(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_t212_client(api_key, api_secret)
    positions_raw = client.get_open_positions()
    positions = []
    for pos in positions_raw:
        inst = pos.get("instrument", {})
        wallet = pos.get("walletImpact", {})
        positions.append({
            "ticker": inst.get("ticker", ""),
            "name": inst.get("name", ""),
            "isin": inst.get("isin", ""),
            "currency": inst.get("currency", ""),
            "quantity": float(pos.get("quantity", 0)),
            "avg_price_paid": float(pos.get("averagePricePaid", 0)),
            "current_price": float(pos.get("currentPrice", 0)),
            "total_cost_gbp": float(wallet.get("totalCost", 0)),
            "current_value_gbp": float(wallet.get("currentValue", 0)),
            "unrealized_pnl_gbp": float(wallet.get("unrealizedProfitLoss", 0)),
            "fx_impact_gbp": float(wallet.get("fxImpact", 0))
        })
    return positions

