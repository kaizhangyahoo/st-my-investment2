"""Mirrors the in-band `data_quality` block to the log.

The services already compute a precise account of what went wrong and hand it to the browser.
Nothing was ever recorded server-side, so a degraded response left no trace once the tab was
closed. This reads that block and logs it; it never mutates it, and no response payload
changes shape.

The consequence sentences match what the sidebar already tells the user, so a log line and a
support screenshot describe the same event in the same words.
"""
import logging
from typing import Any, Dict, List, Mapping

from backend.app.core.tracing import annotate, event

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


def _attributes(surface: str, dq: Mapping[str, Any]) -> Dict[str, Any]:
    """`dq` as span attributes: counts and bounded tuples, never a value passed through.

    Mapped key by key rather than iterated, because the two surfaces hand in different shapes
    and `unconvertible` is a list of dicts, which is not a type a span attribute can hold. A
    key absent from `dq` stays absent here -- `None` is not a legal attribute value either, so
    it would be dropped with a warning rather than recorded.
    """
    attrs: Dict[str, Any] = {
        "data_quality.surface": surface,
        "data_quality.degraded": bool(dq.get("degraded")),
        "data_quality.fx_fallback": bool(dq.get("fx_fallback")),
        "data_quality.reasons": tuple(sorted(f for f in _CONSEQUENCES if dq.get(f))),
    }
    consequence = "; ".join(_consequences(dq))
    if consequence:
        # The same sentence the WARNING carries, so a trace and a support screenshot of the
        # sidebar describe the event in the same words.
        attrs["data_quality.consequence"] = consequence

    unpriced = dq.get("unpriced_tickers") or []
    attrs["data_quality.unpriced_count"] = len(unpriced)
    if unpriced:
        attrs["data_quality.unpriced_tickers"] = tuple(sorted(unpriced)[:_MAX_LISTED])

    unconvertible = dq.get("unconvertible") or []
    attrs["data_quality.unconvertible_count"] = len(unconvertible)
    if unconvertible:
        # Only the currencies: the actionable half, and bounded where the ticker list is not.
        attrs["data_quality.unconvertible_currencies"] = tuple(
            sorted({row.get("currency") or "unknown" for row in unconvertible})
        )

    attrs["data_quality.failure_count"] = len(dq.get("failures") or [])
    for field in ("skipped_dates", "fx_unbacked_dates"):
        if field in dq:
            attrs[f"data_quality.{field}"] = int(dq[field])
    return attrs


def log_data_quality(logger: logging.Logger, surface: str, dq: Mapping[str, Any]) -> None:
    """Log one line describing a response's data quality, and mirror it onto the current span.

    Read-only on `dq`. The span attributes land on the request span -- no manual span is open
    by the time a router reaches here -- so "show me degraded requests" is one Tempo filter.
    Degradation never sets span status: it is a successful response carrying a caveat, and
    marking it an error would make the error rate useless.
    """
    if not dq:
        return

    annotate(**_attributes(surface, dq))

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
        detail = "; ".join(consequences) or "see context for details"
        event("data_quality.degraded", surface=surface, consequence=detail)
        logger.warning(
            "%s is serving degraded data: %s",
            surface,
            detail,
            extra=context,
        )
    elif failures:
        # Something failed but a fallback covered it -- worth a record, not an alarm.
        logger.info(
            "%s recovered from %d provider failure(s)", surface, len(failures), extra=context
        )
    else:
        logger.debug("%s served clean data", surface, extra=context)
