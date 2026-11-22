"""KAN-51: `/trading212/orders` and `/trading212/dividends` as the handlers actually return them.

The transforms are covered in `test/unitTest/test_t212_history.py`. What this adds is the wiring
the UI depends on, and the one thing a unit test cannot see: `response_model` validation. The
schemas these endpoints answer with were dead stubs -- declared, never referenced -- and their
fill fields were non-Optional, so a rejected order would have been rejected by Pydantic rather
than rendered. A passing transform proves nothing if the response model drops or 500s on it.

Driven through the real handler functions with only the API client substituted, so nothing here
reaches Trading 212.
"""
import unittest
from unittest.mock import patch

from backend.app.api.v1 import trading212 as endpoint
from backend.app.schemas.trading212 import T212DividendPage, T212OrderPage, T212Position
from backend.app.core.cache import cache
from backend.app.services import t212_service
from test.support.t212 import (
    POSITION,
    FakeT212Client,
    dividend,
    filled_order,
    page,
    rejected_order,
)

USER = {"sub": "verify-t212-history"}


class EndpointCase(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def serve(self, client):
        patcher = patch.object(t212_service, "get_t212_client", lambda *a, **kw: client)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestOrdersEndpoint(EndpointCase):
    def test_a_rejected_order_survives_response_model_validation(self):
        # The whole reason the schema had to be widened. With the original `price: float` this
        # raises ValidationError and the panel gets a 500 instead of its own order history.
        self.serve(FakeT212Client(order_pages=[page([filled_order(), rejected_order()])]))

        validated = T212OrderPage.model_validate(
            endpoint.get_orders(x_t212_key="k", x_t212_secret="s", user=USER)
        )

        self.assertEqual(len(validated.items), 2)
        rejected = validated.items[1]
        self.assertEqual(rejected.status, "REJECTED")
        self.assertIsNone(rejected.fill_price)
        self.assertIsNone(rejected.net_value)

    def test_the_chart_symbol_reaches_the_response(self):
        # The instrument inspector charts on this field, and it is the only field in the payload
        # that is not a straight copy of something the API said.
        self.serve(FakeT212Client(order_pages=[page([
            filled_order(order_id="1", ticker="ALCC1_US_EQ"),
        ])]))

        validated = T212OrderPage.model_validate(
            endpoint.get_orders(x_t212_key="k", x_t212_secret="s", user=USER)
        )

        self.assertEqual(validated.items[0].symbol, "OKLO")

    def test_every_row_in_the_response_is_uniquely_identifiable(self):
        # The table renders one row per item and needs a stable key for each. `id` cannot supply
        # it: these three rows are three fills of one order.
        self.serve(FakeT212Client(order_pages=[page([
            filled_order(order_id="12402228822", fill_id="7"),
            filled_order(order_id="12402228822", fill_id="8"),
            rejected_order(order_id="59258603081"),
        ])]))

        items = T212OrderPage.model_validate(
            endpoint.get_orders(x_t212_key="k", x_t212_secret="s", user=USER)
        ).items

        keys = [i.fill_id or i.id for i in items]
        self.assertEqual(len(set(keys)), 3, f"duplicate row keys: {keys}")

    def test_truncation_is_reported_to_the_caller(self):
        self.serve(FakeT212Client(order_pages=[
            page([filled_order(order_id=str(i))], next_cursor=i, cursor=i - 1 or None)
            for i in range(1, 9)
        ]))

        validated = T212OrderPage.model_validate(
            endpoint.get_orders(x_t212_key="k", x_t212_secret="s", user=USER)
        )

        self.assertTrue(validated.truncated, "the panel cannot caveat a window it is not told about")

    def test_a_client_failure_becomes_a_400_rather_than_an_unhandled_error(self):
        class Boom(FakeT212Client):
            def get_instruments(self):
                raise RuntimeError("401 Unauthorized")

        self.serve(Boom(order_pages=[page([filled_order()])]))

        # assertLogs both silences the traceback and proves the error was recorded.
        with self.assertLogs("backend.app.api.v1.trading212", level="ERROR") as captured:
            with self.assertRaises(Exception) as caught:
                endpoint.get_orders(x_t212_key="bad", x_t212_secret="bad", user=USER)

        self.assertEqual(getattr(caught.exception, "status_code", None), 400)

        # The provider's own text is for the log, not the client: it can carry upstream detail
        # the browser has no business rendering.
        detail = str(getattr(caught.exception, "detail", ""))
        self.assertNotIn("401", detail)
        self.assertIn("Trading 212 request failed", detail)
        self.assertIn("401 Unauthorized", "\n".join(captured.output))

    def test_the_missing_credentials_message_still_reaches_the_user(self):
        # Unlike a provider error, this one is actionable UI text and is surfaced verbatim.
        self.serve(FakeT212Client(order_pages=[page([filled_order()])]))

        with patch.object(endpoint, "fetch_t212_orders", side_effect=ValueError(
            "Trading 212 API key and secret are required"
        )):
            with self.assertLogs("backend.app.api.v1.trading212", level="ERROR"):
                with self.assertRaises(Exception) as caught:
                    endpoint.get_orders(x_t212_key=None, x_t212_secret=None, user=USER)

        self.assertEqual(getattr(caught.exception, "status_code", None), 400)
        self.assertEqual(
            getattr(caught.exception, "detail", ""),
            "Trading 212 API key and secret are required",
        )


class TestDividendsEndpoint(EndpointCase):
    def test_the_blotter_payload_validates_and_keeps_both_currencies(self):
        self.serve(FakeT212Client(dividend_pages=[page([dividend()])]))

        validated = T212DividendPage.model_validate(
            endpoint.get_dividends(x_t212_key="k", x_t212_secret="s", user=USER)
        )

        div = validated.items[0]
        self.assertEqual(div.instrument_currency, "USD")
        self.assertEqual(div.currency, "GBP")
        self.assertEqual(div.amount, 1.38)

    def test_the_schema_has_no_withholding_or_regime_field(self):
        # Asserted on the contract, not just the dict, so the two unsourceable columns cannot be
        # reintroduced by adding a field with a plausible default.
        for absent in ("wht", "withholding_tax", "tax_regime", "regime"):
            self.assertNotIn(absent, T212DividendPage.model_fields["items"].annotation.__args__[0].model_fields)


class TestPositionsEndpointStillHonoursItsContract(EndpointCase):
    """`symbol` was added to a live schema, so the existing fields must be untouched."""

    def test_the_new_symbol_field_is_additive(self):
        self.serve(FakeT212Client(positions=[POSITION]))

        rows = endpoint.get_positions(x_t212_key="k", x_t212_secret="s", user=USER)
        validated = T212Position.model_validate(rows[0])

        self.assertEqual(validated.symbol, "GOOG")
        self.assertEqual(validated.ticker, "GOOG_US_EQ")
        self.assertEqual(validated.quantity, 13.0)
        self.assertEqual(validated.current_value_gbp, 3086.0)
        self.assertEqual(validated.unrealized_pnl_gbp, 261.0)
        self.assertEqual(validated.fx_impact_gbp, -12.0)

    def test_a_position_on_an_uncovered_venue_still_validates(self):
        unknown = {**POSITION, "ticker": "TVBETNG_EQ",
                   "instrument": {**POSITION["instrument"], "ticker": "TVBETNG_EQ"}}
        self.serve(FakeT212Client(positions=[unknown]))

        rows = endpoint.get_positions(x_t212_key="k", x_t212_secret="s", user=USER)

        self.assertIsNone(T212Position.model_validate(rows[0]).symbol)


if __name__ == "__main__":
    unittest.main()
