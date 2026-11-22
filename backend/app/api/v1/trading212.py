from fastapi import APIRouter, Depends, Header, HTTPException
from typing import List, Dict, Any, Optional
import logging
from backend.app.core.request_context import get_request_id
from backend.app.schemas.trading212 import (
    T212AccountSummary,
    T212DividendPage,
    T212OrderPage,
    T212Position,
)
from backend.app.services.t212_service import (
    fetch_t212_dividends,
    fetch_t212_orders,
    fetch_t212_positions,
    fetch_t212_summary,
)
from backend.app.core.security import get_current_user

router = APIRouter(prefix="/trading212", tags=["trading212"])

logger = logging.getLogger(__name__)

# Actionable UI text, surfaced verbatim by the frontend's apiErrorMessage. Unlike a provider
# error, telling the user this one is the whole point, so it survives genericisation.
_MISSING_CREDENTIALS = "Trading 212 API key and secret are required"


def _fail(operation: str, exc: Exception) -> HTTPException:
    """Record the error, then hand back a 400 that does not republish the exception text."""
    logger.exception("Trading 212 %s failed; the panel will show no data", operation)
    if isinstance(exc, ValueError) and str(exc) == _MISSING_CREDENTIALS:
        return HTTPException(status_code=400, detail=_MISSING_CREDENTIALS)
    request_id = get_request_id()
    suffix = f" (request id {request_id})" if request_id else ""
    return HTTPException(status_code=400, detail=f"Trading 212 request failed{suffix}")

@router.get("/overview", response_model=T212AccountSummary)
def get_overview(
    x_t212_key: Optional[str] = Header(None),
    x_t212_secret: Optional[str] = Header(None),
    user: dict = Depends(get_current_user)
):
    try:
        return fetch_t212_summary(api_key=x_t212_key, api_secret=x_t212_secret)
    except Exception as e:
        raise _fail("overview", e) from e

@router.get("/positions", response_model=List[T212Position])
def get_positions(
    x_t212_key: Optional[str] = Header(None),
    x_t212_secret: Optional[str] = Header(None),
    user: dict = Depends(get_current_user)
):
    try:
        return fetch_t212_positions(api_key=x_t212_key, api_secret=x_t212_secret)
    except Exception as e:
        raise _fail("positions", e) from e

@router.get("/orders", response_model=T212OrderPage)
def get_orders(
    x_t212_key: Optional[str] = Header(None),
    x_t212_secret: Optional[str] = Header(None),
    user: dict = Depends(get_current_user)
):
    try:
        return fetch_t212_orders(api_key=x_t212_key, api_secret=x_t212_secret)
    except Exception as e:
        raise _fail("orders", e) from e

@router.get("/dividends", response_model=T212DividendPage)
def get_dividends(
    x_t212_key: Optional[str] = Header(None),
    x_t212_secret: Optional[str] = Header(None),
    user: dict = Depends(get_current_user)
):
    try:
        return fetch_t212_dividends(api_key=x_t212_key, api_secret=x_t212_secret)
    except Exception as e:
        raise _fail("dividends", e) from e
