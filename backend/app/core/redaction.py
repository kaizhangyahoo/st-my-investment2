"""Keeps credentials out of log lines.

Two layers, because knowing the value is not always possible. The configured secrets are masked
by literal match; anything shaped like `?apikey=...` is masked whether or not the value is one of
ours. The second layer is what covers `price_service` passing `apikey` and `api_token` as query
parameters, since a `requests` exception repr embeds the whole URL the moment a fetch fails.
"""
import re
from typing import Iterable, List, Optional

REDACTED = "[redacted]"

# Catches provider keys in a URL even when the value itself is unknown to us.
_QUERY_SECRET_RE = re.compile(
    r"([?&](?:api_?token|api_?key|apikey|token|secret|password|access_token)=)[^&\s\"']+",
    re.IGNORECASE,
)

_SETTINGS_SECRET_FIELDS = (
    "FIREBASE_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "EODHD_API_TOKEN",
    "FINAGE_API_KEY",
    "TWELVEDATA_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "POLYGON_API_KEY",
    "T212_API_KEY",
    "T212_API_SECRET",
    "JWT_SECRET",
    "OTEL_EXPORTER_OTLP_HEADERS",
)

# Shorter than this and a literal substring replace would mangle unrelated text.
_MIN_SECRET_LEN = 8

_secret_literals: List[str] = []


def collect_secret_literals(settings_obj) -> List[str]:
    """Snapshot the configured secret values once, at logging-configuration time.

    TWELVEDATA_API_KEY holds comma-separated keys for rotation, so split on commas too; the
    OTLP headers value is `Authorization=Basic <token>`, so whitespace and `=` split it as well.
    """
    found = []
    for field in _SETTINGS_SECRET_FIELDS:
        raw = getattr(settings_obj, field, None)
        if not isinstance(raw, str):
            continue
        for part in re.split(r"[,\s]+|(?<=[A-Za-z])=(?=[A-Za-z])", raw):
            part = part.strip()
            if len(part) >= _MIN_SECRET_LEN:
                found.append(part)
    # Longest first so a key that contains another is masked whole.
    return sorted(set(found), key=len, reverse=True)


def set_secret_literals(values: Iterable[str]) -> None:
    global _secret_literals
    _secret_literals = sorted({v for v in values if len(v) >= _MIN_SECRET_LEN}, key=len, reverse=True)


def redact(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    for literal in _secret_literals:
        if literal in text:
            text = text.replace(literal, REDACTED)
    return _QUERY_SECRET_RE.sub(r"\1" + REDACTED, text)
