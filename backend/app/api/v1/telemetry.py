"""Ingest for browser-side log entries.

Deliberately not reusing /auth/log-event: that route is unauthenticated, Firestore-bound and
accepts an arbitrary email.

Every client-supplied value is nested under `context.client`, so a browser cannot set
`severity`, `httpRequest` or the trace key -- those come from the server's own request
context. The client's claim about level is recorded separately from the level actually used.
"""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.app.core.config import settings
from backend.app.core.ratelimit import TokenBucket
from backend.app.core.redaction import redact
from backend.app.core.security import get_current_user
from backend.app.schemas.telemetry import ClientLogBatch

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

logger = logging.getLogger("app.client")

# Secondary guard. The schema's own caps (20 entries, 1 KB message, 4 KB stack) are the
# primary bound; this rejects an oversized body without inspecting its contents.
_MAX_BODY_BYTES = 64 * 1024
_bucket = TokenBucket(capacity=60, refill_seconds=300)


def reject_oversized_body(request: Request) -> None:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Telemetry batch too large")

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


def _user_hash(user: dict) -> str:
    # `sub` is an email on this app's tokens. Keyed, because a plain SHA-256 of an email is
    # reversible by hashing a list of candidate addresses.
    raw = str(user.get("sub") or user.get("email") or "anonymous")
    key = settings.JWT_SECRET.encode("utf-8")
    return hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


@router.post("/client-logs", status_code=204, dependencies=[Depends(reject_oversized_body)])
async def ingest_client_logs(
    batch: ClientLogBatch,
    request: Request,
    user: dict = Depends(get_current_user),
) -> Response:
    user_hash = _user_hash(user)
    client = request.client
    key = f"{user_hash}:{client.host if client else 'unknown'}"

    if not _bucket.allow(key):
        # 204 rather than 429 on purpose: the client must never retry or surface an error for
        # its own telemetry, or a failing page amplifies itself.
        logger.warning(
            "Client log telemetry rate limit reached; entries are being dropped",
            extra={"user_hash": user_hash, "dropped_batch_entries": len(batch.entries)},
        )
        return Response(status_code=204)

    user_agent = redact(request.headers.get("user-agent", ""))[:256]
    for entry in batch.entries:
        logger.log(
            _LEVELS[entry.level],
            "client: %s",
            entry.message,
            extra={
                "client": {
                    # The emitting component; the record itself is shipped by fastapi-portfolio.
                    "service": "web-portfolio",
                    "claimed_level": entry.level,
                    "view": entry.view,
                    "path": entry.path,
                    "client_request_id": entry.request_id,
                    "ts": entry.ts,
                    "count": entry.count,
                    "stack": redact(entry.stack),
                    "release": batch.release,
                    "session_id": batch.session_id,
                },
                "user_hash": user_hash,
                "user_agent": user_agent,
            },
        )
    return Response(status_code=204)
