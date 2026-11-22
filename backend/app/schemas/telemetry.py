from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class ClientLogEntry(BaseModel):
    level: Literal["debug", "info", "warn", "error"]
    message: str = Field(max_length=1000)
    ts: Optional[str] = None
    view: Optional[str] = Field(default=None, max_length=64)
    path: Optional[str] = Field(default=None, max_length=256)
    request_id: Optional[str] = Field(default=None, max_length=64)
    stack: Optional[str] = Field(default=None, max_length=4000)
    # A deduplicated client-side entry stands in for `count` occurrences.
    count: int = Field(default=1, ge=1, le=1000)


class ClientLogBatch(BaseModel):
    entries: List[ClientLogEntry] = Field(max_length=20)
    release: Optional[str] = Field(default=None, max_length=64)
    session_id: Optional[str] = Field(default=None, max_length=64)
