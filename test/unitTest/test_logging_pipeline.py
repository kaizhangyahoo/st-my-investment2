"""The logging pipeline: request correlation, error responses, and redaction before export."""
import logging
import unittest

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from backend.app.core import otel_logs, redaction
from backend.app.core.otel_logs import (
    RedactingOTelHandler,
    _build_exporter,
    build_otel_handler,
    parse_kv,
    resolve_protocol,
)


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


class TestProtocolSelection(unittest.TestCase):
    """Exporter construction opens no connection, so these stay offline."""

    ENDPOINT = "https://gw.invalid/otlp"
    LOGGER = "backend.app.core.otel_logs"

    def test_an_unset_protocol_defaults_to_http_without_complaint(self):
        with self.assertNoLogs(self.LOGGER, "WARNING"):
            self.assertEqual(resolve_protocol(None), "http/protobuf")
            self.assertEqual(resolve_protocol(""), "http/protobuf")

    def test_the_value_is_trimmed_and_case_insensitive(self):
        with self.assertNoLogs(self.LOGGER, "WARNING"):
            self.assertEqual(resolve_protocol("  HTTP/PROTOBUF "), "http/protobuf")

    def test_any_other_transport_is_refused_with_a_warning(self):
        # grpc is the value most likely to be tried: nothing in this project receives OTLP over
        # it, so it must be refused rather than quietly selecting a different exporter.
        for value in ("grpc", "http/json"):
            with self.subTest(value=value):
                with self.assertLogs(self.LOGGER, "WARNING") as captured:
                    self.assertEqual(resolve_protocol(value), "http/protobuf")
                self.assertIn(value, captured.output[0])

    def test_the_exporter_posts_to_the_logs_signal_path(self):
        exporter = _build_exporter(self.ENDPOINT, {"x-extra": "1"})
        self.assertIn(".proto.http.", type(exporter).__module__)
        self.assertEqual(exporter._endpoint, f"{self.ENDPOINT}/v1/logs")


class TestBuildOTelHandler(unittest.TestCase):
    LOGGER = "backend.app.core.otel_logs"

    class SettingsStub:
        OTEL_EXPORTER_OTLP_ENDPOINT = None
        OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
        OTEL_EXPORTER_OTLP_HEADERS = None
        OTEL_RESOURCE_ATTRIBUTES = None
        OTEL_SERVICE_NAME = "test-service"
        ENVIRONMENT = "test"

    def _close_provider_afterwards(self):
        """A successful build leaves a live batch worker and an atexit hook in a module global."""
        def close():
            if otel_logs._provider is not None:
                otel_logs._provider.shutdown()
                otel_logs._provider = None
        self.addCleanup(close)

    def test_offline_mode_returns_none_without_warning(self):
        s = self.SettingsStub()
        with self.assertNoLogs(self.LOGGER, "WARNING"):
            handler = build_otel_handler(s)
        self.assertIsNone(handler)

    def test_headers_without_endpoint_warns_developer(self):
        s = self.SettingsStub()
        s.OTEL_EXPORTER_OTLP_HEADERS = "Authorization=Basic abc"
        with self.assertLogs(self.LOGGER, "WARNING") as captured:
            handler = build_otel_handler(s)
        self.assertIsNone(handler)
        self.assertIn("OTEL_EXPORTER_OTLP_ENDPOINT is missing", captured.output[0])

    def test_grafana_endpoint_without_auth_header_warns_developer(self):
        s = self.SettingsStub()
        # Unroutable, so the built exporter cannot reach the real gateway, while still matching
        # the "grafana.net" substring the warning is keyed on.
        s.OTEL_EXPORTER_OTLP_ENDPOINT = "https://gw.grafana.net.invalid/otlp"
        s.OTEL_EXPORTER_OTLP_HEADERS = ""
        self._close_provider_afterwards()
        with self.assertLogs(self.LOGGER, "WARNING") as captured:
            handler = build_otel_handler(s)
        self.assertIsNotNone(handler)
        self.assertIn("does not contain an Authorization header", captured.output[0])

    def test_handler_carries_the_protocol_actually_exported_over(self):
        s = self.SettingsStub()
        s.OTEL_EXPORTER_OTLP_ENDPOINT = "https://gw.invalid/otlp"
        s.OTEL_EXPORTER_OTLP_HEADERS = "Authorization=Basic abc"
        s.OTEL_EXPORTER_OTLP_PROTOCOL = "grpc"
        self._close_provider_afterwards()
        with self.assertLogs(self.LOGGER, "WARNING"):
            handler = build_otel_handler(s)
        self.assertEqual(handler._pa_protocol, "http/protobuf")

    def test_missing_package_logs_actionable_error(self):
        s = self.SettingsStub()
        s.OTEL_EXPORTER_OTLP_ENDPOINT = "https://gw.invalid/otlp"
        s.OTEL_EXPORTER_OTLP_HEADERS = "Authorization=Basic abc"
        import builtins
        orig_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if "opentelemetry" in name:
                raise ImportError(f"No module named {name}", name=name)
            return orig_import(name, *args, **kwargs)

        builtins.__import__ = failing_import
        try:
            with self.assertLogs(self.LOGGER, "ERROR") as captured:
                handler = build_otel_handler(s)
            self.assertIsNone(handler)
            self.assertIn("pip install -r backend/requirements.txt", captured.output[0])
        finally:
            builtins.__import__ = orig_import


if __name__ == "__main__":
    unittest.main()
