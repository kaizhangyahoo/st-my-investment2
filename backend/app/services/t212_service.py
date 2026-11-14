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
    cash = summary.get("cash") or {}
    inv = summary.get("investments") or {}
    return {
        "id": str(summary.get("id") or "N/A"),
        "currency": str(summary.get("currency") or "GBP"),
        "total_value": float(summary.get("totalValue") or 0.0),
        "cash_available": float(cash.get("availableToTrade") or 0.0),
        "investments_value": float(inv.get("currentValue") or 0.0),
        "unrealized_pnl": float(inv.get("unrealizedProfitLoss") or 0.0),
        "total_cost": float(inv.get("totalCost") or 0.0),
        "realized_pnl": float(inv.get("realizedProfitLoss") or 0.0)
    }

def fetch_t212_positions(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_t212_client(api_key, api_secret)
    positions_raw = client.get_open_positions()
    
    if isinstance(positions_raw, dict):
        if "items" in positions_raw:
            positions_raw = positions_raw["items"]
        elif "errorMessage" in positions_raw or "code" in positions_raw:
            raise ValueError(f"Trading 212 API error: {positions_raw.get('errorMessage') or positions_raw.get('code')}")
        else:
            positions_raw = []
    elif not isinstance(positions_raw, list):
        positions_raw = []

    positions = []
    for pos in positions_raw:
        if not isinstance(pos, dict):
            continue
        inst = pos.get("instrument") or {}
        wallet = pos.get("walletImpact") or {}
        positions.append({
            "ticker": str(inst.get("ticker") or pos.get("ticker") or ""),
            "name": str(inst.get("name") or pos.get("name") or ""),
            "isin": str(inst.get("isin") or pos.get("isin") or ""),
            "currency": str(inst.get("currency") or pos.get("currency") or "GBP"),
            "quantity": float(pos.get("quantity") or 0.0),
            "avg_price_paid": float(pos.get("averagePricePaid") or 0.0),
            "current_price": float(pos.get("currentPrice") or 0.0),
            "total_cost_gbp": float(wallet.get("totalCost") or 0.0),
            "current_value_gbp": float(wallet.get("currentValue") or 0.0),
            "unrealized_pnl_gbp": float(wallet.get("unrealizedProfitLoss") or 0.0),
            "fx_impact_gbp": float(wallet.get("fxImpact") or 0.0)
        })
    return positions
