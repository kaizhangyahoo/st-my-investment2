from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Optional
import logging
from backend.app.schemas.portfolio import ResolveTickersRequest, UpdateMappingsRequest
from backend.app.services.ticker_service import load_ticker_mappings, save_ticker_mappings, resolve_tickers_sec
from backend.app.core.security import get_current_user

router = APIRouter(prefix="/tickers", tags=["tickers"])

logger = logging.getLogger(__name__)

@router.get("/mappings", response_model=Dict[str, str])
def get_mappings(user: dict = Depends(get_current_user)):
    return load_ticker_mappings()

@router.put("/mappings", response_model=Dict[str, str])
def update_mappings(payload: UpdateMappingsRequest, user: dict = Depends(get_current_user)):
    try:
        saved = save_ticker_mappings(payload.mappings, replace=payload.replace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    logger.info(
        "Ticker mappings %s: %d entr(ies) submitted, %d stored",
        "replaced" if payload.replace else "merged",
        len(payload.mappings),
        len(saved),
        extra={"event": "tickers.mappings.updated"},
    )
    return saved

@router.post("/resolve", response_model=Dict[str, Optional[str]])
def resolve_missing(payload: ResolveTickersRequest, user: dict = Depends(get_current_user)):
    return resolve_tickers_sec(payload.market_names)

