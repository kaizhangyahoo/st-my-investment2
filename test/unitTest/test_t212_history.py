"""KAN-51: the Trading 212 order and dividend history transforms.

The panels these feed used to render hardcoded arrays, so what matters here is not that the
mapping runs but that it keeps the parts of a real response the mock data had no notion of: an
order with no fill, a platform ticker that is not a market symbol, and a dividend whose gross
and net are quoted in different currencies.

Every call goes through `FakeT212Client`, so no HTTP is attempted.
"""
import unittest
from unittest.mock import patch

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


class T212Case(unittest.TestCase):
    """Substitutes the client, so `settings.T212_API_KEY` is never read and no socket opens."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def service(self, client):
        patcher = patch.object(t212_service, "get_t212_client", lambda *a, **kw: client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client


class TestOrdersKeepUnfilledOrders(T212Case):
    """The headline finding from the live account: most orders never fill.

    The blotter's old mock gave all five of its rows a price, a quantity and a `FILLED` status.
    Two thirds of the real history is REJECTED or CANCELLED with no `fill` object at all, so any
    mapping that coerced the missing fields to zero would report a rejected order as an execution
    at £0.00 -- indistinguishable from a real trade that happened to settle at nothing.
    """

    def test_a_rejected_order_is_returned_with_null_fill_fields(self):
        client = self.service(FakeT212Client(order_pages=[page([rejected_order()])]))

        order = t212_service.fetch_t212_orders()["items"][0]

        self.assertEqual(order["status"], "REJECTED")
        self.assertIsNone(order["fill_price"], "a rejected order was given an execution price")
        self.assertIsNone(order["filled_at"])
        self.assertIsNone(order["fill_type"])
        self.assertIsNone(order["fees"])
        self.assertIsNone(order["net_value"])
        self.assertIsNone(order["fx_rate"])
        # The order itself still has these, and they are what the row is worth showing for.
        self.assertEqual(order["quantity"], 3.0)
        self.assertEqual(order["side"], "BUY")
        self.assertEqual(order["name"], "Alphabet (Class C)")
        del client

    def test_a_rejected_order_is_not_dropped(self):
        # Filtering them out would be the other tempting fix, and it would quietly hide two
        # thirds of the account's activity from a panel whose title is "Order History".
        self.service(FakeT212Client(order_pages=[page([filled_order(), rejected_order()])]))

        orders = t212_service.fetch_t212_orders()["items"]

        self.assertEqual([o["status"] for o in orders], ["FILLED", "REJECTED"])

    def test_a_filled_order_carries_every_execution_field(self):
        self.service(FakeT212Client(order_pages=[page([filled_order()])]))

        order = t212_service.fetch_t212_orders()["items"][0]

        self.assertEqual(order["fill_price"], 316.77)
        self.assertEqual(order["filled_quantity"], 3.0)
        self.assertEqual(order["filled_at"], "2026-10-26T13:31:06.000Z")
        self.assertEqual(order["fill_type"], "TRADE")
        self.assertEqual(order["net_value"], 713.34)
        self.assertEqual(order["net_currency"], "GBP")
        self.assertEqual(order["currency"], "USD", "the instrument's currency, not the wallet's")
        self.assertAlmostEqual(order["fx_rate"], 1.3341991)

    def test_zero_filled_quantity_survives_rather_than_becoming_null(self):
        # `fill.quantity or order.filledQuantity` is a falsy trap: a partial cancel can legitimately
        # report 0.0, and `or` would fall through it.
        order = filled_order()
        order["fill"]["quantity"] = 0.0
        self.service(FakeT212Client(order_pages=[page([order])]))

        mapped = t212_service.fetch_t212_orders()["items"][0]

        self.assertEqual(mapped["filled_quantity"], 0.0)


class TestRowIdentity(T212Case):
    """One history entry is one fill, so `order.id` is not a row identity.

    A 68-share order in the live account came back as 23 tranches priced 154.14 to 154.18, all
    sharing one `order.id`. The table keys its rows on what this returns, and the duplicate keys
    corrupted React's reconciliation badly enough to leave stale rows behind: filtering to an
    85-row instrument rendered 140 rows, and clearing the filter rendered 315. The fill's own id
    is what makes a row identifiable, so it has to reach the client.
    """

    def test_tranches_of_one_order_are_distinguishable(self):
        self.service(FakeT212Client(order_pages=[page([
            filled_order(order_id="12402228822", fill_id="a", fill_quantity=2.5972762),
            filled_order(order_id="12402228822", fill_id="b", fill_quantity=3.0),
            filled_order(order_id="12402228822", fill_id="c", fill_quantity=2.4027238),
        ])]))

        rows = t212_service.fetch_t212_orders()["items"]

        self.assertEqual([r["id"] for r in rows], ["12402228822"] * 3, "one order, three fills")
        self.assertEqual(len({r["fill_id"] for r in rows}), 3)
        # Each tranche keeps its own quantity; summing them is the order's filled quantity.
        self.assertAlmostEqual(sum(r["filled_quantity"] for r in rows), 8.0)

    def test_an_order_that_never_executed_has_no_fill_id(self):
        self.service(FakeT212Client(order_pages=[page([rejected_order()])]))

        self.assertIsNone(t212_service.fetch_t212_orders()["items"][0]["fill_id"])

    def test_a_numeric_fill_id_is_returned_as_a_string(self):
        # The API sends both ids as JSON numbers; `id` is already declared `str`, so the new field
        # has to match rather than hand the UI a number for one row and a string for the next.
        order = filled_order()
        order["fill"]["id"] = 59307261024
        self.service(FakeT212Client(order_pages=[page([order])]))

        self.assertEqual(t212_service.fetch_t212_orders()["items"][0]["fill_id"], "59307261024")


class TestFees(T212Case):
    """Fees come from the fill's `taxes`, each of which carries its own currency."""

    def test_taxes_are_summed_into_a_signed_total(self):
        self.service(FakeT212Client(order_pages=[page([filled_order()])]))

        self.assertAlmostEqual(t212_service.fetch_t212_orders()["items"][0]["fees"], -1.07)

    def test_a_fill_with_no_taxes_reports_zero_not_null(self):
        # Distinct from a rejected order: this one executed and genuinely cost nothing, which the
        # UI must render as £0.00 rather than as the "no execution" dash.
        self.service(FakeT212Client(order_pages=[page([filled_order(taxes=[])])]))

        self.assertEqual(t212_service.fetch_t212_orders()["items"][0]["fees"], 0.0)

    def test_a_tax_in_another_currency_is_not_added_to_the_wallet_total(self):
        # Adding a USD charge to a GBP one yields a number in neither currency, and the column is
        # labelled with the wallet's.
        self.service(FakeT212Client(order_pages=[page([filled_order(taxes=[
            {"name": "CURRENCY_CONVERSION_FEE", "currency": "GBP", "quantity": -1.07},
            {"name": "FRENCH_TRANSACTION_TAX", "currency": "USD", "quantity": -5.00},
        ])])]))

        self.assertAlmostEqual(t212_service.fetch_t212_orders()["items"][0]["fees"], -1.07)


class TestChartSymbolResolution(T212Case):
    """A T212 ticker is a platform id, so the market symbol has to be looked up.

    This is the reason the instrument metadata endpoint is called at all. Slicing `_US_EQ` off
    the ticker looks equivalent until it charts the wrong company.
    """

    def test_the_symbol_comes_from_short_name_not_from_the_ticker(self):
        # `ALCC1_US_EQ` is Oklo: the id keeps the pre-merger SPAC identity, so string surgery on
        # the ticker would request a price series for a company that no longer exists.
        self.service(FakeT212Client(order_pages=[page([
            filled_order(order_id="1", ticker="ALCC1_US_EQ"),
        ])]))

        self.assertEqual(t212_service.fetch_t212_orders()["items"][0]["symbol"], "OKLO")

    def test_a_london_listing_gets_the_exchange_suffix(self):
        # And nothing in `CNX1_EQ` says London -- only `workingScheduleId` does.
        self.service(FakeT212Client(order_pages=[page([
            filled_order(order_id="1", ticker="CNX1_EQ"),
        ])]))

        self.assertEqual(t212_service.fetch_t212_orders()["items"][0]["symbol"], "CNX1.L")

    def test_an_unmapped_exchange_yields_no_symbol_rather_than_a_guess(self):
        # The price provider does not cover Bucharest. A bare `TVBETNG` would resolve somewhere
        # else entirely, so the honest answer is None and the UI says it cannot chart it.
        self.service(FakeT212Client(order_pages=[page([
            filled_order(order_id="1", ticker="TVBETNG_EQ"),
        ])]))

        self.assertIsNone(t212_service.fetch_t212_orders()["items"][0]["symbol"])

    def test_an_instrument_with_no_working_schedule_is_skipped(self):
        self.service(FakeT212Client(order_pages=[page([
            filled_order(order_id="1", ticker="BROKEN_EQ"),
        ])]))

        self.assertIsNone(t212_service.fetch_t212_orders()["items"][0]["symbol"])

    def test_positions_carry_the_symbol_too(self):
        # The instrument inspector charts from the position row, so the position needs it as well.
        self.service(FakeT212Client(positions=[POSITION]))

        self.assertEqual(t212_service.fetch_t212_positions()[0]["symbol"], "GOOG")


class TestSymbolIndexIsCached(T212Case):
    """18.5k instruments at 1 request / 50s: fetching it per call would rate-limit the page."""

    def test_the_metadata_is_fetched_once_across_several_calls(self):
        client = self.service(FakeT212Client(
            order_pages=[page([filled_order()])],
            dividend_pages=[page([dividend()])],
        ))

        t212_service.fetch_t212_orders()
        t212_service.fetch_t212_dividends()
        t212_service.fetch_t212_orders()

        self.assertEqual(client.calls.count("instruments"), 1)
        self.assertEqual(client.calls.count("exchanges"), 1)

    def test_the_credentials_are_not_part_of_the_cache_key(self):
        # `ttl_cache` builds its key from `str(args)`, which is why the index is cached by hand:
        # decorating a credential-taking function would park the key and secret in a dict that
        # lives for the life of the process.
        client = self.service(FakeT212Client(order_pages=[page([filled_order()])]))
        t212_service.fetch_t212_orders(api_key="public-key", api_secret="secret-value")

        serialised = repr(sorted(cache._store.keys()))

        self.assertNotIn("secret-value", serialised)
        self.assertNotIn("public-key", serialised)
        self.assertIn("t212_chart_symbols", serialised)
        del client


class TestHistoryPagination(T212Case):
    """`nextPagePath` is the only place the cursor is published, so it is parsed back out."""

    def test_pages_are_walked_until_the_api_stops_offering_one(self):
        client = self.service(FakeT212Client(order_pages=[
            page([filled_order(order_id="1")], next_cursor=111),
            page([filled_order(order_id="2")], next_cursor=222, cursor=111),
            page([filled_order(order_id="3")], cursor=222),
        ]))

        result = t212_service.fetch_t212_orders()

        self.assertEqual([o["id"] for o in result["items"]], ["1", "2", "3"])
        self.assertFalse(result["truncated"], "the last page offered no successor")
        self.assertEqual(
            [c for c in client.calls if c.startswith("orders")],
            ["orders:None", "orders:111", "orders:222"],
        )

    def test_stopping_early_is_reported_as_truncated(self):
        # The panel has to be able to say "most recent N only" instead of implying the table is
        # the whole account.
        self.service(FakeT212Client(order_pages=[
            page([filled_order(order_id="1")], next_cursor=111),
            page([filled_order(order_id="2")], next_cursor=222, cursor=111),
        ]))

        result = t212_service.fetch_t212_orders(max_pages=1)

        self.assertEqual([o["id"] for o in result["items"]], ["1"])
        self.assertTrue(result["truncated"])

    def test_a_next_path_without_a_cursor_stops_rather_than_looping(self):
        # Re-requesting cursor=None would otherwise fetch page one forever.
        client = self.service(FakeT212Client(order_pages=[
            {"items": [filled_order(order_id="1")], "nextPagePath": "/api/v0/equity/history/orders"},
        ]))

        result = t212_service.fetch_t212_orders()

        self.assertEqual(len(result["items"]), 1)
        self.assertTrue(result["truncated"])
        self.assertEqual([c for c in client.calls if c.startswith("orders")], ["orders:None"])

    def test_an_empty_history_is_an_empty_page_not_a_failure(self):
        self.service(FakeT212Client(order_pages=[page([])]))

        result = t212_service.fetch_t212_orders()

        self.assertEqual(result, {"items": [], "truncated": False})


class TestDividends(T212Case):
    """Gross and net are quoted in different currencies, which the old mock column conflated."""

    def test_gross_and_net_keep_their_own_currencies(self):
        self.service(FakeT212Client(dividend_pages=[page([dividend()])]))

        div = t212_service.fetch_t212_dividends()["items"][0]

        self.assertEqual(div["gross_per_share"], 0.22)
        self.assertEqual(div["instrument_currency"], "USD")
        self.assertEqual(div["amount"], 1.38)
        self.assertEqual(div["currency"], "GBP")

    def test_no_withholding_or_tax_regime_field_is_invented(self):
        # The blotter used to show "WHT Deducted (15%)" and "Tax Regime". The endpoint returns
        # neither, and the gross-to-net gap is withholding *and* FX together, so there is nothing
        # to derive them from -- the columns had to go rather than be filled with a plausible
        # number.
        self.service(FakeT212Client(dividend_pages=[page([dividend()])]))

        div = t212_service.fetch_t212_dividends()["items"][0]

        for absent in ("wht", "withholding", "withholding_tax", "regime", "tax_regime"):
            self.assertNotIn(absent, div)

    def test_the_payment_type_is_passed_through_verbatim(self):
        # Live values are `DIVIDEND` and `RETURN_OF_CAPITAL`; the mock's `ORDINARY` and
        # `DISTRIBUTION` were invented, so nothing here may normalise or relabel them.
        self.service(FakeT212Client(dividend_pages=[page([
            dividend(), dividend(ticker="TRI_US_EQ", div_type="RETURN_OF_CAPITAL"),
        ])]))

        types = [d["type"] for d in t212_service.fetch_t212_dividends()["items"]]

        self.assertEqual(types, ["DIVIDEND", "RETURN_OF_CAPITAL"])

    def test_the_paid_on_timestamp_is_not_truncated_server_side(self):
        # It arrives with an offset (`+03:00`). Cutting it to a date here would silently shift a
        # late-evening payment by a day for anyone reading it in another zone; the UI formats it.
        self.service(FakeT212Client(dividend_pages=[page([dividend()])]))

        self.assertEqual(
            t212_service.fetch_t212_dividends()["items"][0]["paid_on"],
            "2026-09-14T14:01:44.000+03:00",
        )


if __name__ == "__main__":
    unittest.main()
