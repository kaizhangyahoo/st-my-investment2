"""KAN-18: latency guards on the cold dashboard load.

The headline defect was ~180s of hardcoded `time.sleep(60)` between TwelveData batches,
which made a cold load take ~188s instead of ~2s. These tests assert on elapsed-time
*causes* (sleep calls, request counts, fan-out width) rather than on wall-clock, so they
stay deterministic on a loaded CI box.
"""
import unittest
from unittest.mock import patch

from backend.app.services import price_service
from test.support.stubs import response, session_stub, yahoo_quote


class TestNoBlockingSleep(unittest.TestCase):
    def test_no_sleep_between_twelvedata_batches(self):
        symbols = [f"S{i:02d}" for i in range(1, 17)]  # 16 symbols -> 2 batches of 8
        payload = {s: {"close": "10.0"} for s in symbols}

        session, calls = session_stub(twelvedata=lambda url, kw: response(payload=payload))
        with patch.object(price_service, "_session", session), \
                patch.object(price_service, "_twelvedata_keys", lambda: ["fake-key"]), \
                patch.object(price_service.time, "sleep") as mock_sleep:
            prices, failures = price_service.fetch_us_prices(symbols)

        mock_sleep.assert_not_called()
        self.assertEqual(len(calls), 2)
        self.assertEqual(failures, [])
        self.assertEqual(len(prices), 16)


class TestRequestBudget(unittest.TestCase):
    """What a load costs in provider requests. Ordering/correctness is covered in
    functionalTest/test_price_fallback_chain.py."""

    def test_batching_keeps_twelvedata_requests_sublinear(self):
        """8 symbols per request on the free tier -- 24 symbols must cost 3 calls, not 24."""
        symbols = [f"S{i:02d}" for i in range(24)]
        payload = {s: {"close": "10.0"} for s in symbols}

        session, calls = session_stub(twelvedata=lambda url, kw: response(payload=payload))
        with patch.object(price_service, "_session", session), \
                patch.object(price_service, "_twelvedata_keys", lambda: ["fake-key"]):
            price_service.fetch_us_prices(symbols)

        self.assertEqual(len(calls), 3)

    def test_yahoo_fan_out_is_bounded(self):
        """Unbounded parallelism gets the IP rate-limited, which is how KAN-18 started."""
        self.assertEqual(price_service._MAX_PARALLEL_FETCHES, 8)
        self.assertEqual(price_service._TWELVEDATA_BATCH, 8)


class TestTimeoutsAreSet(unittest.TestCase):
    """Every outbound call needs a timeout, or a hung provider hangs the dashboard."""

    def test_every_provider_request_passes_a_timeout(self):
        seen = []

        def record(url, kw):
            seen.append(kw.get("timeout"))
            return response(payload=yahoo_quote(200.0))

        session, _ = session_stub(yahoo=record)
        with patch.object(price_service, "_session", session):
            price_service.get_prices(["AAPL"])

        self.assertEqual(seen, [price_service.TIMEOUT])
        self.assertLessEqual(price_service.TIMEOUT, 30)


if __name__ == "__main__":
    unittest.main()
