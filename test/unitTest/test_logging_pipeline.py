"""The logging pipeline: request correlation, the emitted line's shape, and redaction on both
the stdout and the OTLP export path."""
import json
import logging
import sys
import unittest
from unittest import mock

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from backend.app.core import otel_logs, redaction
from backend.app.core.logging_config import JsonFormatter, TextFormatter
from backend.app.core.otel_logs import (
    RedactingOTelHandler,
    _build_exporter,
    build_otel_handler,
    parse_kv,
    resolve_protocol,
)
from backend.app.core.request_context import parse_cloud_trace


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

    def test_the_access_line_carries_latency_as_a_number_as_well_as_a_string(self):
        """`httpRequest.latency` is a duration string because Cloud Logging parses it that way,
        which leaves a Grafana latency panel scraping `"0.412s"` out of text. The numeric
        sibling has to sit outside that dict -- the field names in it are Google's."""
        with self.assertLogs("app.access", level="INFO") as captured:
            self.assertEqual(self.client.get("/api/ok").status_code, 200)

        record = captured.records[-1]
        self.assertIsInstance(record.duration_ms, float)
        self.assertGreaterEqual(record.duration_ms, 0.0)
        self.assertRegex(record.http_request["latency"], r"^\d+\.\d{3}s$")
        self.assertNotIn("duration_ms", record.http_request)


class TestCloudTraceHeaderShape(unittest.TestCase):
    """`X-Cloud-Trace-Context` is the only id source when no span is sampled, so on Cloud Run
    with tracing off a log line joins through this header or not at all."""

    TRACE = "105445aa7843bc8bf206b12000100000"

    def test_the_decimal_span_id_google_sends_becomes_sixteen_hex_digits(self):
        trace, span = parse_cloud_trace(f"{self.TRACE}/1;o=1")
        self.assertEqual(trace, self.TRACE)
        # Not "1". Google writes this half in decimal; W3C and Cloud Logging's `spanId` both
        # read hex, so the id as sent joins to nothing.
        self.assertEqual(span, "0000000000000001")

    def test_a_full_width_span_id_round_trips(self):
        _trace, span = parse_cloud_trace(f"{self.TRACE}/13448908014500269201")
        self.assertEqual(span, format(13448908014500269201, "016x"))
        self.assertRegex(span, r"^[0-9a-f]{16}$")

    def test_the_sampling_suffix_and_surrounding_space_are_ignored(self):
        self.assertEqual(
            parse_cloud_trace(f" {self.TRACE} / 255 ;o=0"), (self.TRACE, format(255, "016x"))
        )

    def test_a_span_half_that_is_not_a_64_bit_decimal_is_dropped_rather_than_passed_on(self):
        # The header is client-settable, and a mis-shaped id is worse than none: it joins to
        # nothing while looking like it should.
        for value in ("abc", "-1", "1.5", "0x1f", str(2 ** 64), ""):
            with self.subTest(span=value):
                trace, span = parse_cloud_trace(f"{self.TRACE}/{value}")
                self.assertEqual(trace, self.TRACE, "the trace half must survive regardless")
                self.assertIsNone(span)

    def test_nothing_is_invented_when_the_header_carries_no_trace(self):
        for header in (None, "", ";o=1", "/1"):
            with self.subTest(header=header):
                self.assertEqual(parse_cloud_trace(header), (None, None))


class TestJsonLogLineShape(unittest.TestCase):
    """The Cloud Logging structured-log contract. Every field name here is Google's, so a
    rename silently downgrades the entry to unparsed text instead of failing anything."""

    PROJECT = "project-e29b631c"

    def _record(self, **extra):
        record = logging.LogRecord(
            "app.access", logging.WARNING, "/srv/app/main.py", 42, "served %s",
            ("/api/ok",), None, "_log",
        )
        record.__dict__.update(extra)
        return record

    def _format(self, project_id=PROJECT, **extra):
        return json.loads(JsonFormatter(project_id).format(self._record(**extra)))

    def test_the_contract_fields_are_present_under_the_names_google_reads(self):
        payload = self._format()
        self.assertEqual(payload["severity"], "WARNING")
        self.assertEqual(payload["message"], "served /api/ok")
        self.assertEqual(payload["logger"], "app.access")
        self.assertRegex(payload["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

        location = payload["logging.googleapis.com/sourceLocation"]
        self.assertEqual(location["file"], "/srv/app/main.py")
        self.assertEqual(location["function"], "_log")
        # A string, deliberately: Cloud Logging types sourceLocation.line as one and drops a
        # number, so this is not a stray str() waiting to be tidied away.
        self.assertEqual(location["line"], "42")
        self.assertIsInstance(location["line"], str)

    def test_a_level_name_outside_the_map_degrades_to_DEFAULT_not_to_a_near_match(self):
        payload = self._format(levelname="WARN")
        self.assertEqual(payload["severity"], "DEFAULT")

    def test_the_trace_is_a_project_qualified_resource_name(self):
        payload = self._format(trace_id="a" * 32, span_id="0000000000000001")
        self.assertEqual(
            payload["logging.googleapis.com/trace"],
            f"projects/{self.PROJECT}/traces/{'a' * 32}",
        )
        self.assertEqual(payload["logging.googleapis.com/spanId"], "0000000000000001")

    def test_a_span_id_is_dropped_along_with_the_trace_when_the_project_is_unknown(self):
        """The span id is emitted inside the trace id's own `if`, so it is only ever visible
        with a project configured -- which is what makes the ids' shape testable at all."""
        payload = self._format(project_id=None, trace_id="a" * 32, span_id="0000000000000001")
        self.assertNotIn("logging.googleapis.com/trace", payload)
        self.assertNotIn("logging.googleapis.com/spanId", payload)
        # And it does not fall through into the custom dimensions as a consolation prize.
        self.assertNotIn("span_id", payload.get("context", {}))

    def test_a_trace_with_no_span_still_joins(self):
        payload = self._format(trace_id="a" * 32)
        self.assertIn("logging.googleapis.com/trace", payload)
        self.assertNotIn("logging.googleapis.com/spanId", payload)

    def test_the_numeric_duration_lands_in_context_and_not_in_httpRequest(self):
        payload = self._format(
            http_request={"requestMethod": "GET", "requestUrl": "/api/ok", "status": 200,
                          "latency": "0.412s"},
            duration_ms=412.0,
            request_id="abc1234567890def",
        )
        self.assertEqual(payload["httpRequest"]["latency"], "0.412s")
        self.assertNotIn("duration_ms", payload["httpRequest"])
        self.assertEqual(payload["context"]["duration_ms"], 412.0)
        self.assertIsInstance(payload["context"]["duration_ms"], float)
        self.assertEqual(payload["context"]["request_id"], "abc1234567890def")

    def test_no_reserved_record_attribute_leaks_into_the_custom_dimensions(self):
        payload = self._format(
            http_request={"status": 200}, trace_id="a" * 32, span_id="b" * 16,
            request_id="abc1234567890def", duration_ms=1.0,
        )
        self.assertEqual(set(payload["context"]), {"request_id", "duration_ms"})

    def test_context_is_omitted_when_there_is_nothing_to_put_in_it(self):
        self.assertNotIn("context", self._format())


class TestStdoutPathRedaction(unittest.TestCase):
    """`TestOTelExportRedaction` covers the OTLP path only, and the two are genuinely
    asymmetric: stdout gets a redacted `stack_trace` field of its own and text mode inlines the
    traceback, while the OTLP handler folds it onto the body and has no `stack_trace` at all.
    """

    SECRET = "glc_super-secret-key-123"
    PROJECT = "project-e29b631c"

    def setUp(self):
        redaction.set_secret_literals([self.SECRET])
        self.addCleanup(redaction.set_secret_literals, [])

    def _record(self):
        try:
            raise ValueError(
                f"GET https://api.twelvedata.com/eod?apikey={self.SECRET}&symbol=AAPL failed"
            )
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            "app.price", logging.ERROR, "/srv/app/price.py", 7,
            "provider call failed with key %s", (self.SECRET,), exc_info, "fetch",
        )
        record.request_id = "abc1234567890def"
        record.provider_url = f"https://x.test/q?api_token={self.SECRET}"
        # The shape `log_data_quality` really passes: a list of failure records whose reason is
        # `str(e)` on a requests error, so the leak is two levels down rather than in a string.
        record.failures = [
            {"ticker": "AAPL", "provider": "twelvedata",
             "reason": f"request failed: GET https://api.twelvedata.com/eod?apikey={self.SECRET}"},
        ]
        record.duration_ms = 412.0
        return record

    def test_the_json_line_redacts_the_message_the_traceback_and_the_dimensions(self):
        payload = json.loads(JsonFormatter(self.PROJECT).format(self._record()))

        self.assertNotIn(self.SECRET, json.dumps(payload))
        self.assertIn("[redacted]", payload["message"])
        # The traceback is a field in its own right on this path, and `str(e)` on a requests
        # error carries the whole URL, `apikey=` included.
        self.assertIn("ValueError", payload["stack_trace"])
        self.assertIn("[redacted]", payload["stack_trace"])
        self.assertIn("[redacted]", payload["context"]["provider_url"])
        self.assertIn("[redacted]", payload["context"]["failures"][0]["reason"])
        # Redacting must not coerce the dimensions it is walking past.
        self.assertEqual(payload["context"]["duration_ms"], 412.0)
        self.assertEqual(payload["context"]["failures"][0]["ticker"], "AAPL")

    def test_the_text_line_redacts_the_message_the_traceback_and_the_dimensions(self):
        line = TextFormatter().format(self._record())

        self.assertNotIn(self.SECRET, line)
        self.assertIn("ValueError", line)
        self.assertIn("[redacted]", line)

    def test_a_query_key_is_only_caught_with_its_separator(self):
        """A scope note rather than an endorsement: the URL pattern needs a leading `?` or `&`,
        so a bare `apikey=` in prose survives unless the literal itself is registered."""
        self.assertIn("[redacted]", redaction.redact("GET /x?apikey=abcdef123456"))
        self.assertEqual(redaction.redact("apikey=abcdef123456"), "apikey=abcdef123456")


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class _StubExporter:
    """Enough of the exporter protocol for `BatchLogRecordProcessor`'s worker and its flush,
    so a provider can be built and torn down without an exporter that opens sockets."""

    def export(self, batch):
        return None

    def force_flush(self, timeout_millis=30_000):
        return True

    def shutdown(self):
        return None


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


class TestExporterHandoff(unittest.TestCase):
    """What actually leaves the process. On the installed SDK the exporter's only public members
    are export/force_flush/shutdown, and by the time the headers reach its client they are
    lowercased and merged with defaults -- so the handoff is asserted where the dict still
    carries the casing .env gave it, which is what `_build_exporter` is a function for.
    """

    LOGGER = "backend.app.core.otel_logs"
    # Unroutable, while still matching the "grafana.net" substring the auth warning keys on.
    ENDPOINT = "https://otlp-gateway-prod.grafana.net.invalid/otlp"

    def setUp(self):
        self.built = []
        patcher = mock.patch.object(otel_logs, "_build_exporter", self._record)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._close_provider)

    def _record(self, endpoint, headers):
        self.built.append((endpoint, dict(headers)))
        return _StubExporter()

    def _close_provider(self):
        if otel_logs._provider is not None:
            otel_logs._provider.shutdown()
            otel_logs._provider = None

    def _settings(self, **overrides):
        s = TestBuildOTelHandler.SettingsStub()
        s.OTEL_EXPORTER_OTLP_ENDPOINT = self.ENDPOINT
        s.OTEL_EXPORTER_OTLP_HEADERS = "Authorization=Basic%20MTIzNDU2Nzg6Z2xjX3Rva2Vu"
        for key, value in overrides.items():
            setattr(s, key, value)
        return s

    def test_the_env_headers_arrive_with_their_casing_and_padding_intact(self):
        build_otel_handler(self._settings(
            OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20YWJj==,X-Scope-OrgID=42",
        ))
        endpoint, headers = self.built[0]

        # The signal path suffix is appended by `_build_exporter`, not by the caller.
        self.assertEqual(endpoint, self.ENDPOINT)
        self.assertEqual(headers, {"Authorization": "Basic YWJj==", "X-Scope-OrgID": "42"})

    def test_a_lowercase_authorization_header_is_not_announced_as_missing(self):
        """HTTP header names are case-insensitive and `parse_kv` keeps whatever .env wrote, so
        this exports perfectly well -- and used to warn about a 401 that never came."""
        with self.assertNoLogs(self.LOGGER, "WARNING"):
            handler = build_otel_handler(self._settings(
                OTEL_EXPORTER_OTLP_HEADERS="authorization=Basic%20YWJj",
            ))

        self.assertIsNotNone(handler)
        self.assertEqual(self.built[0][1], {"authorization": "Basic YWJj"})

    def test_an_authorization_header_with_no_value_is_still_announced(self):
        with self.assertLogs(self.LOGGER, "WARNING") as captured:
            build_otel_handler(self._settings(OTEL_EXPORTER_OTLP_HEADERS="Authorization="))
        self.assertIn("does not contain an Authorization header", captured.output[0])

    def test_the_service_name_setting_wins_while_the_environment_can_be_overridden(self):
        """Asymmetric on purpose: `service.name` is what every Grafana query groups by, so it
        is a hard overwrite, whereas `deployment.environment` is a default worth overriding."""
        build_otel_handler(self._settings(
            OTEL_RESOURCE_ATTRIBUTES="service.name=impostor,deployment.environment=staging,"
                                     "service.version=1.4.2",
        ))
        attributes = otel_logs._provider.resource.attributes

        self.assertEqual(attributes["service.name"], "test-service")
        self.assertEqual(attributes["deployment.environment"], "staging")
        self.assertEqual(attributes["service.version"], "1.4.2")

    def test_the_environment_falls_back_to_the_setting_when_nothing_overrides_it(self):
        build_otel_handler(self._settings())
        self.assertEqual(
            otel_logs._provider.resource.attributes["deployment.environment"], "test"
        )


class TestStartupAnnouncement(unittest.TestCase):
    """The one line an operator reads to answer "is this shipping logs?".

    It lives inside `configure_logging`, which also swaps the root handler, sets the root level
    and snapshots the secret literals -- and `main.py` has already run it once at import. So all
    of that is saved and restored around each case.
    """

    ENDPOINT = "https://otlp-gateway-prod.grafana.net.invalid/otlp"
    HEADERS = "Authorization=Basic%20MTIzNDU2Nzg6Z2xjX3Rva2Vu"

    def setUp(self):
        from backend.app.core import logging_config

        self.logging_config = logging_config
        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        literals = list(redaction._secret_literals)

        def restore():
            for handler in list(root.handlers):
                if handler not in handlers:
                    root.removeHandler(handler)
            for handler in handlers:
                if handler not in root.handlers:
                    root.addHandler(handler)
            root.setLevel(level)
            redaction.set_secret_literals(literals)
            if otel_logs._provider is not None:
                otel_logs._provider.shutdown()
                otel_logs._provider = None

        self.addCleanup(restore)
        self._patch(otel_logs, "_build_exporter", lambda endpoint, headers: _StubExporter())

    def _patch(self, target, attribute, value):
        patcher = mock.patch.object(target, attribute, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _configure(self, **settings_overrides):
        for key, value in settings_overrides.items():
            self._patch(self.logging_config.settings, key, value)
        with self.assertLogs("app.startup", "INFO") as captured:
            self.logging_config.configure_logging()
        self.assertEqual(len(captured.records), 1)
        return captured.records[0]

    def test_the_line_names_the_endpoint_the_service_and_the_transport(self):
        record = self._configure(
            OTEL_EXPORTER_OTLP_ENDPOINT=self.ENDPOINT,
            OTEL_EXPORTER_OTLP_HEADERS=self.HEADERS,
        )
        announced = record.getMessage()

        self.assertEqual(record.levelno, logging.INFO)
        self.assertIn(self.ENDPOINT, announced)
        self.assertIn(self.logging_config.settings.OTEL_SERVICE_NAME, announced)
        self.assertIn("http/protobuf", announced)

    def test_the_line_reports_the_transport_used_rather_than_the_one_requested(self):
        """`grpc` is refused and http/protobuf substituted, so echoing the setting back would
        tell an operator the opposite of what is happening. Pinned so nobody "fixes" it."""
        record = self._configure(
            OTEL_EXPORTER_OTLP_ENDPOINT=self.ENDPOINT,
            OTEL_EXPORTER_OTLP_HEADERS=self.HEADERS,
            OTEL_EXPORTER_OTLP_PROTOCOL="grpc",
        )
        self.assertIn("http/protobuf", record.getMessage())
        self.assertNotIn("grpc", record.getMessage())

    def test_an_unconfigured_process_says_so_calmly(self):
        record = self._configure(
            OTEL_EXPORTER_OTLP_ENDPOINT=None, OTEL_EXPORTER_OTLP_HEADERS=None
        )
        self.assertEqual(record.levelno, logging.INFO)
        self.assertIn("stdout", record.getMessage())

    def test_a_configured_endpoint_that_failed_to_build_is_a_warning_not_silence(self):
        """The case an operator most needs and until now the only one with no line at all:
        the endpoint is set, the handler build failed, and silence read as healthy."""
        self._patch(self.logging_config, "build_otel_handler", lambda settings: None)
        record = self._configure(
            OTEL_EXPORTER_OTLP_ENDPOINT=self.ENDPOINT,
            OTEL_EXPORTER_OTLP_HEADERS=self.HEADERS,
        )

        self.assertEqual(record.levelno, logging.WARNING)
        self.assertIn("configured but inactive", record.getMessage())


if __name__ == "__main__":
    unittest.main()
