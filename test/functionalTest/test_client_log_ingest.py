"""The browser log ingest route, which had no behavioural test at all.

The only test naming `/telemetry/client-logs` asserts it is *excluded from tracing* -- the
opposite concern. This is the one route where a value an untrusted browser chose reaches a log
line, so what matters is the properties that stop it choosing the wrong thing: the server picks
the severity, the user is a keyed hash rather than an address, and a render loop is shed rather
than amplified.

Three behaviours contradict the obvious guess and are pinned for that reason -- a *missing*
bearer header is the anonymous dev fallback rather than a 401, going over budget answers 204
rather than 429, and the 20-entry cap is a schema bound and so a 422 rather than the 413 the
byte guard produces.

Offline by construction: no provider is reachable from this route.
"""
import hashlib
import hmac
import json
import logging
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - httpx/fastapi absent
    TestClient = None

from backend.app.api.v1 import telemetry
from backend.app.core.config import settings
from backend.app.core.logging_config import JsonFormatter
from backend.app.core.ratelimit import TokenBucket
from backend.app.core.security import create_access_token

LOGGER = "app.client"
URL = "/api/v1/telemetry/client-logs"
EMAIL = "someone@example.test"
MAX_BODY_BYTES = 64 * 1024


def _entry(**overrides):
    entry = {"level": "info", "message": "chart failed to render"}
    entry.update(overrides)
    return entry


class _Case(unittest.TestCase):
    def setUp(self):
        from backend.app.main import app

        self.client = TestClient(app)
        self.auth = {"Authorization": f"Bearer {create_access_token({'sub': EMAIL})}"}
        # The bucket is a module global and survives the test that spent its tokens.
        self.addCleanup(telemetry._bucket.reset)

    def post(self, entries=None, headers=None, **kwargs):
        body = {"entries": [_entry()] if entries is None else entries}
        return self.client.post(URL, json=body, headers={**self.auth, **(headers or {})}, **kwargs)

    def post_capturing(self, entries=None, **kwargs):
        with self.assertLogs(LOGGER, logging.DEBUG) as captured:
            res = self.post(entries, **kwargs)
        return res, captured.records


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestWhoMayPost(_Case):
    def test_an_invalid_bearer_token_is_rejected(self):
        res = self.client.post(
            URL, json={"entries": [_entry()]}, headers={"Authorization": "Bearer not.a.jwt"}
        )

        self.assertEqual(res.status_code, 401)

    def test_a_request_with_no_bearer_header_is_served_as_the_local_dev_user(self):
        """Not a 401, which is what a reader of the route would assume. `get_current_user`
        hands back an anonymous `dev@local.host` when the header is absent, so the route
        accepts unauthenticated telemetry and hashes the literal fallback identity. That is
        KAN-61's to change; asserted here so the change is a visible test failure."""
        with self.assertLogs(LOGGER, logging.DEBUG) as captured:
            res = self.client.post(URL, json={"entries": [_entry()]})

        self.assertEqual(res.status_code, 204)
        self.assertEqual(
            captured.records[0].user_hash,
            hmac.new(
                settings.JWT_SECRET.encode("utf-8"), b"dev@local.host", hashlib.sha256
            ).hexdigest()[:12],
        )


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestTheServerPicksTheSeverity(_Case):
    def test_the_level_is_the_servers_and_the_clients_claim_is_only_recorded(self):
        res, records = self.post_capturing([_entry(level="warn")])

        self.assertEqual(res.status_code, 204)
        self.assertEqual(records[0].levelno, logging.WARNING)
        self.assertEqual(records[0].client["claimed_level"], "warn")

    def test_a_level_outside_the_four_is_refused_rather_than_mapped(self):
        """`_LEVELS` would KeyError on anything else, so the schema's Literal is load-bearing:
        "critical" is a 422 and never a nearest-match to ERROR."""
        self.assertEqual(self.post([_entry(level="critical")]).status_code, 422)
        self.assertEqual(self.post([_entry(level="INFO")]).status_code, 422)

    def test_a_browser_cannot_forge_severity_or_the_access_line(self):
        res, records = self.post_capturing(
            [_entry(level="info", severity="CRITICAL", httpRequest={"status": 500})]
        )
        line = json.loads(JsonFormatter("test-project").format(records[0]))

        self.assertEqual(res.status_code, 204)
        # Unknown keys are dropped by the schema, so they never reach `extra` to collide with
        # a reserved Cloud Logging field.
        self.assertEqual(line["severity"], "INFO")
        self.assertNotIn("httpRequest", line)
        self.assertNotIn("CRITICAL", json.dumps(line))
        self.assertEqual(line["context"]["client"]["claimed_level"], "info")

    def test_the_line_is_marked_as_the_browsers_and_not_the_servers_own(self):
        _, records = self.post_capturing()

        self.assertEqual(records[0].name, LOGGER)
        self.assertTrue(records[0].getMessage().startswith("client: "))
        self.assertEqual(records[0].client["service"], "web-portfolio")


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestTheUserIsNotIdentifiable(_Case):
    def test_the_line_carries_a_short_keyed_hash_and_never_the_address(self):
        """`sub` is an email on this app's tokens, so an unkeyed digest would be reversible by
        hashing a list of candidate addresses. The HMAC is what makes the hash safe to ship."""
        _, records = self.post_capturing()
        line = json.dumps(json.loads(JsonFormatter("test-project").format(records[0])))

        expected = hmac.new(
            settings.JWT_SECRET.encode("utf-8"), EMAIL.encode("utf-8"), hashlib.sha256
        ).hexdigest()[:12]
        self.assertEqual(records[0].user_hash, expected)
        self.assertEqual(len(records[0].user_hash), 12)
        self.assertNotEqual(
            records[0].user_hash, hashlib.sha256(EMAIL.encode("utf-8")).hexdigest()[:12]
        )
        self.assertNotIn(EMAIL, line)
        self.assertNotIn("someone", line)


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestAFloodIsShedNotAmplified(_Case):
    def test_over_budget_answers_204_and_logs_what_it_dropped(self):
        """204 rather than 429 on purpose: a client that surfaced an error for its own
        telemetry would make a failing page report its own failure to report."""
        with patch.object(telemetry, "_bucket", TokenBucket(capacity=1, refill_seconds=300)):
            with self.assertLogs(LOGGER, logging.DEBUG) as captured:
                first = self.post([_entry(level="debug")])
                second = self.post([_entry(level="debug"), _entry(level="debug")])

        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        # One line for the entry that fit, then one line standing in for the batch that did not.
        self.assertEqual(len(captured.records), 2)
        dropped = captured.records[-1]
        self.assertEqual(dropped.levelno, logging.WARNING)
        self.assertIn("dropped", dropped.getMessage())
        self.assertEqual(dropped.dropped_batch_entries, 2)
        self.assertEqual(len(dropped.user_hash), 12)

    def test_the_budget_is_sixty_posts_per_five_minutes(self):
        """Generous for telemetry -- one post every five seconds, sustained -- and tight enough
        that a render loop stops costing log volume within seconds."""
        self.assertEqual(telemetry._bucket.capacity, 60)
        self.assertAlmostEqual(telemetry._bucket.refill_rate, 60 / 300)


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestTheBodyBounds(_Case):
    def _oversized_body(self):
        body = json.dumps(
            {"entries": [_entry(stack="x" * 4000) for _ in range(20)]}
        ).encode("utf-8")
        # A schema-valid batch really can exceed the byte budget: 20 x (1 KB message + 4 KB
        # stack) is well past 64 KB, so the secondary guard is not unreachable.
        self.assertGreater(len(body), MAX_BODY_BYTES)
        return body

    def test_a_batch_past_the_byte_budget_is_rejected(self):
        res = self.client.post(
            URL,
            content=self._oversized_body(),
            headers={**self.auth, "content-type": "application/json"},
        )

        self.assertEqual(res.status_code, 413)

    def test_only_the_declared_length_is_read_so_a_forged_header_is_enough(self):
        """The guard's real contract. It never measures the body, so a one-entry batch with a
        lying `content-length` is rejected -- harmless, but it is the same fact as the gap
        below, stated from the side that is easy to demonstrate."""
        res = self.post(headers={"content-length": str(MAX_BODY_BYTES + 1)})

        self.assertEqual(res.status_code, 413)

    def test_a_chunked_body_bypasses_the_byte_guard_entirely(self):
        """The limit worth knowing about: with no `content-length` to read, the 64 KB bound does
        not apply at all and only the schema's own caps hold. Acceptable because those caps are
        the primary bound, but it means the byte guard is a courtesy, not a defence."""
        body = self._oversized_body()

        with self.assertLogs(LOGGER, logging.DEBUG) as captured:
            res = self.client.post(
                URL,
                content=iter([body]),
                headers={**self.auth, "content-type": "application/json"},
            )

        self.assertEqual(res.status_code, 204)
        self.assertEqual(len(captured.records), 20)

    def test_a_twenty_first_entry_is_a_schema_error_not_a_byte_one(self):
        res = self.post([_entry() for _ in range(21)])

        self.assertEqual(res.status_code, 422)

    def test_a_full_twenty_entry_batch_is_accepted_and_logged_one_line_each(self):
        res, records = self.post_capturing([_entry() for _ in range(20)])

        self.assertEqual(res.status_code, 204)
        self.assertEqual(len(records), 20)


if __name__ == "__main__":
    unittest.main()
