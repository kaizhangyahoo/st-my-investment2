"""P4: `SERVICE_ROLE=trading212` serves only the Trading212 routes."""
import importlib
import unittest

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from backend.app.core.config import settings


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class Trading212RoleCase(unittest.TestCase):
    def _paths(self, role: str) -> set:
        import backend.app.main as main

        previous = settings.SERVICE_ROLE
        settings.SERVICE_ROLE = role
        try:
            module = importlib.reload(main)
            paths = set(module.app.openapi()["paths"])
            paths.add("/health")  # defined on the app, so present in every role
            return paths
        finally:
            settings.SERVICE_ROLE = previous
            importlib.reload(main)

    def test_trading212_role_mounts_only_trading212(self):
        paths = self._paths("trading212")
        self.assertTrue(any("/trading212/" in p for p in paths))
        self.assertFalse(any("/portfolio" in p or "/market-data" in p or "/internal" in p for p in paths))
        self.assertIn("/health", paths)

    def test_monolith_still_mounts_trading212(self):
        self.assertTrue(any("/trading212/" in p for p in self._paths("all")))


if __name__ == "__main__":
    unittest.main()
