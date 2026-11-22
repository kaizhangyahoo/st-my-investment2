"""Keeps credentials out of log lines.

Two layers, because headers are not the only leak path. `price_service` passes `apikey` and
`api_token` as query parameters, and a `requests` exception repr embeds the full URL — so a
header allowlist alone would still publish a provider key the moment a fetch fails.
"""
import re
from typing import Dict, Iterable, List, Mapping, Optional

REDACTED = "[redacted]"

# Read off a request only these. An allowlist means a sensitive header added later cannot
# leak by default, which a denylist would not guarantee.
SAFE_REQUEST_HEADERS = frozenset({
    "user-agent",
    "referer",
    "content-type",
    "content-length",
    "x-request-id",
    "x-cloud-trace-context",
})

SENSITIVE_HEADERS = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-t212-key",
    "x-t212-secret",
})

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


def safe_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    """Project request headers down to the allowlist."""
    return {k: v for k, v in headers.items() if k.lower() in SAFE_REQUEST_HEADERS}


def redact_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    """Mask known-sensitive headers but keep the rest. For explicit debugging use."""
    return {k: (REDACTED if k.lower() in SENSITIVE_HEADERS else v) for k, v in headers.items()}
