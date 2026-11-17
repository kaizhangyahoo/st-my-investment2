"""KAN-12: `resolve_ticker` in isolation -- chain-following and the blank-mapping rule."""
import unittest

from backend.app.services.ticker_service import resolve_ticker


class TestResolveTicker(unittest.TestCase):
    def test_remap_chain_resolves_to_the_final_ticker(self):
        """Corporate-action chains must be followed, not read one hop deep (KAN-11)."""
        mappings = {"Skillz Inc": "SKLZ", "SKLZ": "FIRY"}
        self.assertEqual(resolve_ticker("Skillz Inc", mappings), "FIRY")

    def test_chain_is_followed_through_several_hops(self):
        mappings = {"Old Name": "A", "A": "B", "B": "C"}
        self.assertEqual(resolve_ticker("Old Name", mappings), "C")

    def test_a_cyclic_chain_terminates(self):
        """A self-referential map must not hang the upload path."""
        self.assertEqual(resolve_ticker("A", {"A": "B", "B": "A"}), "A")

    def test_absent_name_is_unresolved(self):
        self.assertIsNone(resolve_ticker("Bogus Ltd", {"Apple Inc": "AAPL"}))

    def test_null_mapping_is_unresolved(self):
        self.assertIsNone(resolve_ticker("Bogus Ltd", {"Bogus Ltd": None}))

    def test_blank_mapping_is_unresolved(self):
        """Without this the engine groups trades under '' and invents a phantom position."""
        self.assertIsNone(resolve_ticker("Bogus Ltd", {"Bogus Ltd": "   "}))

    def test_a_blank_mapping_is_not_chained_through(self):
        """A blank key must not become a hop. `Bogus Ltd -> "" -> AAPL` would otherwise
        silently file these trades under an unrelated holding."""
        self.assertIsNone(resolve_ticker("Bogus Ltd", {"Bogus Ltd": "", "": "AAPL"}))


if __name__ == "__main__":
    unittest.main()
