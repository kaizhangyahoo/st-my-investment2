from fastapi import APIRouter, Depends, Header, HTTPException
from typing import List, Dict, Any, Optional
from backend.app.schemas.trading212 import T212AccountSummary, T212Position
from backend.app.services.t212_service import fetch_t212_summary, fetch_t212_positions
from backend.app.core.security import get_current_user

router = APIRouter(prefix="/trading212", tags=["trading212"])

@router.get("/overview", response_model=T212AccountSummary)
def get_overview(
    x_t212_key: Optional[str] = Header(None),
    x_t212_secret: Optional[str] = Header(None),
    user: dict = Depends(get_current_user)
):
    try:
        return fetch_t212_summary(api_key=x_t212_key, api_secret=x_t212_secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/positions", response_model=List[T212Position])
def get_positions(
    x_t212_key: Optional[str] = Header(None),
    x_t212_secret: Optional[str] = Header(None),
    user: dict = Depends(get_current_user)
):
    try:
        return fetch_t212_positions(api_key=x_t212_key, api_secret=x_t212_secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

