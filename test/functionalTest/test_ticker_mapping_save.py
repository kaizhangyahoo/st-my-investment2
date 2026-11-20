"""`PUT /tickers/mappings`: merge vs replace, and the validation that guards the file.

Driven through the real `tickers.update_mappings` handler against a temp mapping file.
"""
import unittest

from fastapi import HTTPException

from backend.app.api.v1 import tickers
from backend.app.schemas.portfolio import UpdateMappingsRequest
from backend.app.services.ticker_service import load_ticker_mappings
from test.support.portfolio import TempMappingCase


class TestMappingSave(TempMappingCase):
    MAPPINGS = {"Apple Inc": "AAPL", "Skillz Inc": "SKLZ", "SKLZ": "FIRY"}
    USER = {"sub": "verify-ticker-mapping-save"}

    def _put(self, mappings, replace=False):
        payload = UpdateMappingsRequest(mappings=mappings, replace=replace)
        return tickers.update_mappings(payload=payload, user=self.USER)

    def _assert_rejected(self, mappings, replace=False):
        with self.assertRaises(HTTPException) as ctx:
            self._put(mappings, replace=replace)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(load_ticker_mappings(), self.MAPPINGS, "file must be untouched")

    def test_merge_keeps_entries_missing_from_the_payload(self):
        self._put({"Bogus Ltd": "BOGUS.L"})
        self.assertEqual(load_ticker_mappings(), {**self.MAPPINGS, "Bogus Ltd": "BOGUS.L"})

    def test_replace_persists_a_delete(self):
        self._put({"Apple Inc": "AAPL"}, replace=True)
        self.assertEqual(load_ticker_mappings(), {"Apple Inc": "AAPL"})

    def test_replace_persists_a_rename_without_leaving_the_old_key(self):
        self._put({"Apple Inc.": "AAPL", "Skillz Inc": "SKLZ", "SKLZ": "FIRY"}, replace=True)
        self.assertNotIn("Apple Inc", load_ticker_mappings())
        self.assertEqual(load_ticker_mappings()["Apple Inc."], "AAPL")

    def test_tickers_are_trimmed_and_uppercased_but_names_kept_verbatim(self):
        self._put({"Bogus Ltd": "  bogus.l "})
        self.assertEqual(load_ticker_mappings()["Bogus Ltd"], "BOGUS.L")

    def test_blank_ticker_is_rejected(self):
        self._assert_rejected({"Bogus Ltd": "   "})

    def test_blank_name_is_rejected(self):
        self._assert_rejected({"  ": "AAPL"})

    def test_case_variant_of_a_stored_name_is_rejected_on_merge(self):
        self._assert_rejected({"apple  inc": "AAPL"})

    def test_case_variants_within_one_payload_are_rejected(self):
        self._assert_rejected({"Apple Inc": "AAPL", "APPLE INC": "AAPL"}, replace=True)

    def test_updating_an_exact_existing_name_is_allowed(self):
        self._put({"Apple Inc": "AAPL.MX"})
        self.assertEqual(load_ticker_mappings()["Apple Inc"], "AAPL.MX")


if __name__ == "__main__":
    unittest.main()
