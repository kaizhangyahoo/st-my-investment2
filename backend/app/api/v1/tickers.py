from fastapi import APIRouter, Depends
from typing import Dict, List, Optional
from backend.app.schemas.portfolio import ResolveTickersRequest, UpdateMappingsRequest
from backend.app.services.ticker_service import load_ticker_mappings, save_ticker_mappings, resolve_tickers_sec
from backend.app.core.security import get_current_user

router = APIRouter(prefix="/tickers", tags=["tickers"])

@router.get("/mappings", response_model=Dict[str, str])
def get_mappings(user: dict = Depends(get_current_user)):
    return load_ticker_mappings()

@router.put("/mappings", response_model=Dict[str, str])
def update_mappings(payload: UpdateMappingsRequest, user: dict = Depends(get_current_user)):
    return save_ticker_mappings(payload.mappings)

@router.post("/resolve", response_model=Dict[str, Optional[str]])
def resolve_missing(payload: ResolveTickersRequest, user: dict = Depends(get_current_user)):
    return resolve_tickers_sec(payload.market_names)

