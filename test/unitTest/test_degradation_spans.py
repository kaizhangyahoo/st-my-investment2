"""A degraded response has to be findable in Tempo, not just in the logs.

`log_data_quality` already turns the in-band `data_quality` block into one log line. These tests
cover the span half of the same account: the reason and consequence as attributes, an event
marking the moment, a status that stays OK because degradation is a successful response carrying
a caveat -- and the log line itself, which had no coverage at all before this file.
"""
import copy
import logging
import unittest

try:
    from opentelemetry.trace import StatusCode
except ImportError:  # pragma: no cover
    StatusCode = None

from backend.app.core import otel_traces
from backend.app.core.diagnostics import log_data_quality
from test.support.tracing import (
    MAX_LISTED,
    TRACING_AVAILABLE,
    TracedApp,
    assert_attributes_are_safe,
    assert_status_not_error,
)

SURFACE = "portfolio.history.compute"

# The shape `history_service` produces. `unconvertible` is a list of dicts, which is the reason
# the mapper cannot pass `dq` values through: OpenTelemetry has no attribute type for it.
DEGRADED = {
    "degraded": True,
    "fx_fallback": True,
    "skipped_dates": 3,
    "fx_unbacked_dates": 2,
    "unpriced_tickers": ["BBB", "AAA"],
    "unconvertible": [
        {"ticker": "XXX", "currency": "SEK"},
        {"ticker": "YYY", "currency": "SEK"},
        {"ticker": "ZZZ", "currency": None},
    ],
}

# The shape `portfolio_engine` produces -- different keys, and a provider failure that a
# fallback covered, so `degraded` is False.
RECOVERED = {
    "degraded": False,
    "fx_fallback": False,
    "unpriced_tickers": [],
    "failures": [{"provider": "yahoo", "ticker": "AAA", "reason": "timeout"}],
}

CLEAN = {"degraded": False, "fx_fallback": False, "unpriced_tickers": [], "failures": []}


def _log(dq, surface=SURFACE):
    """Returns the records `log_data_quality` emitted, so the log and the span can be pinned in
    the same test and neither can drift without the other failing."""
    logger = logging.getLogger("test.diagnostics")
    with unittest.TestCase().assertLogs(logger, logging.DEBUG) as captured:
        log_data_quality(logger, surface, dq)
    return captured.records


@unittest.skipIf(not TRACING_AVAILABLE, "fastapi / opentelemetry sdk unavailable")
class TestDegradationSpans(TracedApp):
    def setUp(self):
        self.dq = {}
        self.records = []
        self._build(lambda: self._handler(), path="/api/dq")

    def _handler(self):
        self.records = _log(self.dq)
        return {"ok": True}

    def _request(self, dq):
        self.dq = dq
        self.assertEqual(self.client.get(self.path).status_code, 200)
        return self.server_span()

    def test_the_span_carries_the_reasons_and_the_logs_own_sentence(self):
        server = self._request(DEGRADED)
        attrs = server.attributes

        self.assertIs(attrs["data_quality.degraded"], True)
        self.assertEqual(attrs["data_quality.surface"], SURFACE)
        self.assertEqual(
            attrs["data_quality.reasons"],
            ("fx_fallback", "fx_unbacked_dates", "skipped_dates", "unconvertible",
             "unpriced_tickers"),
        )
        # Same words as the WARNING, so a trace and a support screenshot agree.
        self.assertEqual(
            attrs["data_quality.consequence"], self.records[0].getMessage().split(": ", 1)[1]
        )
        self.assertEqual(attrs["data_quality.unpriced_count"], 2)
        self.assertEqual(attrs["data_quality.unpriced_tickers"], ("AAA", "BBB"))
        self.assertEqual(attrs["data_quality.unconvertible_count"], 3)
        self.assertEqual(attrs["data_quality.skipped_dates"], 3)
        self.assertEqual(attrs["data_quality.fx_unbacked_dates"], 2)

    def test_a_degraded_response_is_not_an_error(self):
        server = self._request(DEGRADED)
        self.assertEqual(self.records[0].levelno, logging.WARNING)
        self.assertIsNot(server.status.status_code, StatusCode.ERROR)
        assert_status_not_error(self, self.spans())

    def test_only_the_degraded_branch_adds_an_event(self):
        server = self._request(DEGRADED)
        events = [e for e in server.events if e.name == "data_quality.degraded"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].attributes["surface"], SURFACE)
        self.assertEqual(
            events[0].attributes["consequence"], server.attributes["data_quality.consequence"]
        )

        for dq, level in ((RECOVERED, logging.INFO), (CLEAN, logging.DEBUG)):
            self.exporter.clear()
            server = self._request(dq)
            self.assertEqual(self.records[0].levelno, level)
            self.assertEqual(server.events, ())
            # Still annotated, so "clean" is assertable rather than merely absent.
            self.assertIs(server.attributes["data_quality.degraded"], False)
            self.assertNotIn("data_quality.consequence", server.attributes)

    def test_a_recovered_response_counts_the_failures_without_describing_them(self):
        server = self._request(RECOVERED)
        self.assertEqual(server.attributes["data_quality.failure_count"], 1)
        # The reason string embeds whatever the provider said, including its URL and api key.
        assert_attributes_are_safe(self, self.spans(), forbidden=("timeout", "yahoo"))

    def test_an_unbounded_ticker_list_is_truncated_and_dicts_never_appear_verbatim(self):
        dq = {**DEGRADED, "unpriced_tickers": [f"T{i:03d}" for i in range(50)]}
        server = self._request(dq)

        self.assertEqual(server.attributes["data_quality.unpriced_count"], 50)
        self.assertEqual(len(server.attributes["data_quality.unpriced_tickers"]), MAX_LISTED)
        # Only the currencies: bounded where the ticker list is not, and the actionable half.
        self.assertEqual(
            server.attributes["data_quality.unconvertible_currencies"], ("SEK", "unknown")
        )
        assert_attributes_are_safe(self, self.spans(), forbidden=("XXX", "YYY", "ZZZ"))

    def test_the_block_it_reads_is_left_alone(self):
        before = copy.deepcopy(DEGRADED)
        self._request(DEGRADED)
        self.assertEqual(DEGRADED, before)


class TestDegradationWhileTracingIsOff(unittest.TestCase):
    """The state every other suite runs in. The event is guarded on the provider rather than by
    a method on the `_NoSpan` stub, so this is what pins that choice: routing it through the
    stub instead fails here with AttributeError."""

    def setUp(self):
        self.saved, otel_traces._provider = otel_traces._provider, None

    def tearDown(self):
        otel_traces._provider = self.saved

    def test_logging_degradation_without_a_provider_is_silent_and_unchanged(self):
        for dq in (DEGRADED, RECOVERED, CLEAN):
            records = _log(dq)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0].getMessage())

    def test_an_empty_block_logs_nothing(self):
        logger = logging.getLogger("test.diagnostics.empty")
        with self.assertNoLogs(logger, logging.DEBUG):
            log_data_quality(logger, SURFACE, {})


if __name__ == "__main__":
    unittest.main()
