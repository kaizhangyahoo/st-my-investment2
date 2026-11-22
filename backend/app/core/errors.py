"""Exception handlers that feed the access log without changing any response body.

4xx reasons are stashed on `request.state` and printed on the middleware's single access line,
so a rejected request is one log entry rather than two. Unhandled exceptions are dealt with in
`RequestContextMiddleware`, not here: an app-level `Exception` handler runs in Starlette's
outermost middleware, after the request id has been unbound.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException):
        request.state.error_detail = exc.detail
        if exc.status_code >= 500:
            logger.error(
                "%s %s failed with %s: %s",
                request.method,
                request.url.path,
                exc.status_code,
                exc.detail,
            )
        # Delegate so the response body stays byte-identical to today's.
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # Locations only. The values are user CSV cells and, on the Trading 212 routes,
        # credentials -- neither belongs in a log line.
        locations = [".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()]
        request.state.error_detail = f"validation failed at {', '.join(locations) or '<unknown>'}"
        return await request_validation_exception_handler(request, exc)
