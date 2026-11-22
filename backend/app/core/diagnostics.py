"""Mirrors the in-band `data_quality` block to the log.

The services already compute a precise account of what went wrong and hand it to the browser.
Nothing was ever recorded server-side, so a degraded response left no trace once the tab was
closed. This reads that block and logs it; it never mutates it, and no response payload
changes shape.

The consequence sentences match what the sidebar already tells the user, so a log line and a
support screenshot describe the same event in the same words.
"""
import logging
from typing import Any, List, Mapping

# Beyond this, log the count and a sample rather than a wall of tickers.
_MAX_LISTED = 20

_CONSEQUENCES = {
    "fx_fallback": "non-GBP valuations are estimates, not real quotes",
    "unpriced_tickers": "market value, P&L and totals are understated",
    "unconvertible": "holdings in an unsupported currency are excluded from the total",
    "skipped_dates": "the equity curve has gaps",
    "fx_unbacked_dates": "some dates have no real FX close behind them",
}


def _sample(values: Any) -> Any:
    if isinstance(values, list) and len(values) > _MAX_LISTED:
        return values[:_MAX_LISTED] + [f"... and {len(values) - _MAX_LISTED} more"]
    return values


def _consequences(dq: Mapping[str, Any]) -> List[str]:
    out = []
    for field, sentence in _CONSEQUENCES.items():
        if dq.get(field):
            out.append(sentence)
    return out


def log_data_quality(logger: logging.Logger, surface: str, dq: Mapping[str, Any]) -> None:
    """Log one line describing a response's data quality. Read-only on `dq`."""
    if not dq:
        return

    context = {
        "surface": surface,
        **{k: _sample(v) for k, v in dq.items() if k not in ("degraded", "failures")},
    }
    failures = dq.get("failures")
    if failures:
        context["failure_count"] = len(failures)
        context["failures"] = _sample(failures)

    if dq.get("degraded"):
        consequences = _consequences(dq)
        logger.warning(
            "%s is serving degraded data: %s",
            surface,
            "; ".join(consequences) or "see context for details",
            extra=context,
        )
    elif failures:
        # Something failed but a fallback covered it -- worth a record, not an alarm.
        logger.info(
            "%s recovered from %d provider failure(s)", surface, len(failures), extra=context
        )
    else:
        logger.debug("%s served clean data", surface, extra=context)
