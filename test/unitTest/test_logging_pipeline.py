"""The logging pipeline: request correlation, error responses, and redaction before export."""
import logging
import unittest

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from backend.app.core import redaction
from backend.app.core.otel_logs import RedactingOTelHandler, parse_kv


def _app():
    from backend.app.core.errors import install_exception_handlers
    from backend.app.core.middleware import RequestContextMiddleware

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)

    @app.get("/api/ok")
    def ok():
        return {"ok": True}

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("kaboom")

    @app.get("/api/denied")
    def denied():
        raise HTTPException(status_code=403, detail="not yours")

    return app


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestRequestCorrelation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_app(), raise_server_exceptions=False)

    def test_a_well_formed_inbound_id_is_echoed(self):
        res = self.client.get("/api/ok", headers={"X-Request-ID": "abc12345-def"})
        self.assertEqual(res.headers["x-request-id"], "abc12345-def")

    def test_a_malformed_inbound_id_is_replaced(self):
        res = self.client.get("/api/ok", headers={"X-Request-ID": "bad id\nInjected: yes"})
        self.assertRegex(res.headers["x-request-id"], r"^[0-9a-f]{16}$")

    def test_an_unhandled_error_returns_the_id_it_was_logged_under(self):
        with self.assertLogs("app.access", level="ERROR") as captured:
            res = self.client.get("/api/boom")
        self.assertEqual(res.status_code, 500)
        request_id = res.headers["x-request-id"]
        self.assertEqual(res.json(), {"detail": "Internal server error", "request_id": request_id})
        self.assertTrue(any("kaboom" in line for line in captured.output))
        self.assertNotIn("kaboom", res.text)

    def test_a_4xx_is_one_access_line_carrying_the_reason(self):
        with self.assertLogs(level="WARNING") as captured:
            res = self.client.get("/api/denied")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json(), {"detail": "not yours"})
        self.assertEqual(len(captured.records), 1)
        self.assertIn("403", captured.output[0])
        self.assertIn("not yours", captured.output[0])


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestOTelExportRedaction(unittest.TestCase):
    def setUp(self):
        redaction.set_secret_literals(["super-secret-key-123"])
        self.addCleanup(redaction.set_secret_literals, [])
        self.inner = _Capture()
        self.logger = logging.getLogger("test.otel.redaction")
        self.logger.propagate = False
        handler = RedactingOTelHandler(self.inner)
        self.logger.addHandler(handler)
        self.addCleanup(self.logger.removeHandler, handler)

    def test_message_exception_and_extras_are_redacted_before_export(self):
        try:
            raise ValueError("GET https://x.test/eod?apikey=abc123&symbol=AAPL failed")
        except ValueError:
            self.logger.exception(
                "call with %s", "super-secret-key-123", extra={"ctx": {"url": "?token=zzz999"}}
            )

        record = self.inner.records[0]
        body = record.getMessage()
        self.assertNotIn("super-secret-key-123", body)
        self.assertNotIn("abc123", body)
        self.assertIn("[redacted]", body)
        self.assertIsNone(record.exc_info)
        self.assertNotIn("zzz999", record.ctx)

    def test_the_exporters_own_logs_are_not_reexported(self):
        logging.getLogger("opentelemetry.exporter.test").addHandler(RedactingOTelHandler(self.inner))
        logging.getLogger("opentelemetry.exporter.test").error("export failed")
        self.assertEqual(self.inner.records, [])


class TestParseKv(unittest.TestCase):
    def test_otlp_headers_value_keeps_the_space_and_padding(self):
        self.assertEqual(
            parse_kv("Authorization=Basic%20YWJj==,x-extra=1"),
            {"Authorization": "Basic YWJj==", "x-extra": "1"},
        )

    def test_the_otlp_header_token_is_registered_for_redaction(self):
        class S:
            OTEL_EXPORTER_OTLP_HEADERS = "Authorization=Basic MTIzNDU2Nzg6Z2xjX3NlY3JldA=="

        self.assertIn("MTIzNDU2Nzg6Z2xjX3NlY3JldA==", redaction.collect_secret_literals(S()))


if __name__ == "__main__":
    unittest.main()
