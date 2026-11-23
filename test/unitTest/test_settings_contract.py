"""KAN-63: the settings class must really read .env and the environment.

`pydantic.BaseModel` reads neither, so the `try/except ImportError` this replaces turned a missing
dependency into an app that starts cleanly with every API key `None` and the hardcoded dev
`JWT_SECRET` live. Nothing anywhere said so, and the symptom was indistinguishable from a provider
outage. The import is now unguarded; these pin both halves -- a missing dependency raises, and a
present one is genuinely wired to the environment rather than merely declaring that it is.
"""
import importlib
import os
import sys
import unittest
from unittest.mock import patch

import pydantic_settings

from backend.app.core import config

MODULE = "backend.app.core.config"


class TestAMissingDependencyIsLoud(unittest.TestCase):
    def test_a_missing_pydantic_settings_fails_the_import_instead_of_degrading(self):
        """`None` in `sys.modules` is how CPython models "present but unimportable", so this
        drives the real import line rather than a stand-in for it. The pre-fix module imported
        cleanly here and every field fell back to its default.
        """
        with patch.dict(sys.modules, {"pydantic_settings": None}):
            sys.modules.pop(MODULE, None)

            with self.assertRaises(ImportError):
                importlib.import_module(MODULE)

        # patch.dict restores sys.modules wholesale, so the rest of the suite keeps the module
        # object it already imported instead of a second, separately-populated Settings.
        self.assertIs(sys.modules[MODULE], config)


class TestSettingsReadTheEnvironment(unittest.TestCase):
    def test_settings_is_a_real_settings_class_and_not_a_bare_basemodel(self):
        self.assertTrue(issubclass(config.Settings, pydantic_settings.BaseSettings))

    def test_an_environment_variable_overrides_the_insecure_jwt_default(self):
        """Asserted on `JWT_SECRET` because it is the field where losing the environment is worse
        than an outage: the default is a publicly-known signing secret, so tokens would be minted
        and accepted against it. Removing that default altogether is KAN-61's.
        """
        with patch.dict(os.environ, {"JWT_SECRET": "from-the-environment"}):
            fresh = config.Settings()

        self.assertEqual(fresh.JWT_SECRET, "from-the-environment")
        self.assertNotEqual(fresh.JWT_SECRET, config.Settings.model_fields["JWT_SECRET"].default)

    def test_the_configured_env_file_still_resolves_to_backend_env(self):
        """`env_file` is built from literal `..` segments off this module's own path, so moving
        config.py would stop .env being read with no error at all -- the same all-defaults failure
        this ticket is about, reached a different way. Existence is not asserted: .env is untracked.
        """
        self.assertEqual(
            os.path.realpath(config.Settings.model_config["env_file"]),
            os.path.realpath(os.path.join(config.settings.REPO_ROOT, "backend", ".env")),
        )

    def test_an_undeclared_env_key_is_ignored_rather_than_fatal(self):
        """backend/.env is shared with tooling that sets keys this class does not declare, and
        `extra="forbid"` would turn any one of them into a crash at import.
        """
        with patch.dict(os.environ, {"A_KEY_SETTINGS_DOES_NOT_DECLARE": "x"}):
            config.Settings()

        self.assertEqual(config.Settings.model_config["extra"], "ignore")


if __name__ == "__main__":
    unittest.main()
