"""`backend.app.core.http.PropagatingSession` sends the headers that make a cross-service join possible.

Nothing calls this client yet -- it is P1 scaffolding for the P2 service split -- so these tests
are the only thing holding its contract. They drive a real `requests.Session` with the adapter
stubbed out, rather than asserting against a hand-rolled header dict, because the bug worth
catching is one where the headers are assembled correctly and then dropped on the way to the
wire.
"""
import re
import unittest
from unittest import mock

try:
    import requests
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
except ImportError:  # pragma: no cover
    requests = None

from backend.app.core import request_context

if requests is not None:
    from backend.app.core.http import DEFAULT_TIMEOUT, PropagatingSession, current_traceparent

TRACEPARENT = re.compile(r"\A00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]\Z")

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"


class Recorder:
    """Answers any request without a socket, keeping what was about to be sent."""

    def __init__(self):
        self.sent = []
        self.kwargs = []

    def send(self, request, **kwargs):
        self.sent.append(request)
        self.kwargs.append(kwargs)
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response._content = b"{}"
        return response


@unittest.skipIf(requests is None, "requests/opentelemetry not installed")
class PropagatingSessionTest(unittest.TestCase):
    def setUp(self):
        self.recorder = Recorder()
        patcher = mock.patch.object(
            requests.adapters.HTTPAdapter, "send", self.recorder.send
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session = PropagatingSession()
        self.addCleanup(self.session.close)

    def _get(self, **kwargs):
        self.session.get("http://portfolio-api.internal/health", **kwargs)
        return self.recorder.sent[-1].headers

    def test_the_request_id_crosses_the_wire(self):
        tokens = request_context.bind_request("abcdef0123456789")
        self.addCleanup(request_context.reset_request, tokens)

        self.assertEqual(self._get()["X-Request-ID"], "abcdef0123456789")

    def test_no_request_id_header_outside_a_request(self):
        # A background task or a startup probe has no correlation id. Sending an empty or invented
        # one would fail the receiving middleware's pattern check and buy nothing.
        self.assertNotIn("X-Request-ID", self._get())

    def test_an_explicit_request_id_is_not_overwritten(self):
        tokens = request_context.bind_request("abcdef0123456789")
        self.addCleanup(request_context.reset_request, tokens)

        headers = self._get(headers={"x-request-id": "caller-supplied-00"})

        self.assertEqual(headers["X-Request-ID"], "caller-supplied-00")
        # Case-insensitively, so the caller's spelling does not end up alongside ours.
        self.assertEqual(
            [name for name in headers if name.lower() == "x-request-id"], ["x-request-id"]
        )

    def test_traceparent_comes_from_the_inbound_cloud_trace_ids(self):
        tokens = request_context.bind_request("abcdef0123456789", TRACE_ID, SPAN_ID)
        self.addCleanup(request_context.reset_request, tokens)

        traceparent = self._get()["traceparent"]

        self.assertEqual(traceparent, f"00-{TRACE_ID}-{SPAN_ID}-01")
        self.assertRegex(traceparent, TRACEPARENT)

    def test_a_misshaped_trace_id_sends_no_traceparent(self):
        # `X-Cloud-Trace-Context` is client-settable and `parse_cloud_trace` deliberately passes
        # the trace half through unvalidated. A receiver may reject a malformed header and start a
        # fresh trace, which breaks the join more quietly than sending nothing.
        tokens = request_context.bind_request("abcdef0123456789", "not-a-trace-id", SPAN_ID)
        self.addCleanup(request_context.reset_request, tokens)

        self.assertNotIn("traceparent", self._get())

    def test_a_missing_span_id_sends_no_traceparent(self):
        tokens = request_context.bind_request("abcdef0123456789", TRACE_ID, None)
        self.addCleanup(request_context.reset_request, tokens)

        self.assertNotIn("traceparent", self._get())

    def test_the_live_span_wins_over_the_inbound_header(self):
        """The ids a span reaches Tempo under are the only ones the next service can join to.

        Same ordering rule as `RequestContextFilter`: a `traceparent` carrying the inbound
        header's ids would point at a trace that was never exported.
        """
        tokens = request_context.bind_request("abcdef0123456789", TRACE_ID, SPAN_ID)
        self.addCleanup(request_context.reset_request, tokens)
        provider = TracerProvider()
        self.addCleanup(provider.shutdown)

        with provider.get_tracer(__name__).start_as_current_span("outbound") as active:
            headers = self._get()
            context = active.get_span_context()

        self.assertEqual(
            headers["traceparent"],
            f"00-{trace.format_trace_id(context.trace_id)}"
            f"-{trace.format_span_id(context.span_id)}-01",
        )
        self.assertNotIn(TRACE_ID, headers["traceparent"])

    def test_no_trace_context_at_all_sends_no_traceparent(self):
        self.assertIsNone(current_traceparent())

    def test_a_default_timeout_is_applied(self):
        self._get()
        self.assertEqual(self.recorder.kwargs[-1]["timeout"], DEFAULT_TIMEOUT)

    def test_an_explicit_timeout_wins(self):
        self._get(timeout=0.5)
        self.assertEqual(self.recorder.kwargs[-1]["timeout"], 0.5)


if __name__ == "__main__":
    unittest.main()
