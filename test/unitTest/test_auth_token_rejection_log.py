"""A rejected bearer token used to be entirely silent.

`decode_access_token` collapsed every PyJWT failure into `return None`, so a user whose tab had
been open too long and somebody forging a signature produced byte-identical server behaviour and
no record of either. The exception *class* is the whole signal; the message and the token are
withheld on purpose, a token being a credential.

Behaviour is unchanged by design -- the broad except, the 401 and the anonymous fallback all
belong to KAN-61. These tests pin that too, so a log line cannot quietly become a redirect.
"""
import logging
import unittest
from datetime import timedelta

import jwt

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.app.core.config import settings
from backend.app.core.security import (
    create_access_token,
    decode_access_token,
    get_current_user,
)

LOGGER = "backend.app.core.security"
# Long enough that PyJWT does not add an InsecureKeyLengthWarning to the suite's output.
OTHER_SECRET = "a-completely-different-secret-key-not-the-apps-one"


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestRejectedTokenIsNamedByItsCause(unittest.TestCase):
    def _reject(self, token: str) -> logging.LogRecord:
        with self.assertLogs(LOGGER, logging.WARNING) as captured:
            self.assertIsNone(decode_access_token(token))
        self.assertEqual(len(captured.records), 1)
        return captured.records[0]

    def test_an_expired_token_and_a_forged_one_are_told_apart(self):
        """The distinction the bare except destroyed: one is routine, the other is an attack."""
        expired = create_access_token({"sub": "u1"}, expires_delta=timedelta(seconds=-10))
        forged = jwt.encode(
            {"sub": "u1"}, OTHER_SECRET, algorithm=settings.JWT_ALGORITHM
        )

        self.assertIn("ExpiredSignatureError", self._reject(expired).getMessage())
        self.assertIn("InvalidSignatureError", self._reject(forged).getMessage())

    def test_a_malformed_token_is_named_rather_than_lumped_in_with_the_rest(self):
        self.assertIn("DecodeError", self._reject("not.a.jwt").getMessage())

    def test_neither_the_token_nor_the_signing_secret_reaches_the_line(self):
        forged = jwt.encode({"sub": "u1"}, OTHER_SECRET, algorithm="HS256")
        message = self._reject(forged).getMessage()

        self.assertNotIn(forged, message)
        # Nor any slice of it long enough to be replayed, hence no claim and no fragment.
        self.assertNotIn(forged.split(".")[1], message)
        self.assertNotIn(settings.JWT_SECRET, message)
        self.assertIn("401", message)

    def test_a_valid_token_decodes_without_a_word(self):
        token = create_access_token({"sub": "u1"})
        with self.assertNoLogs(LOGGER, logging.DEBUG):
            self.assertEqual(decode_access_token(token)["sub"], "u1")


class TestTheLineDidNotChangeTheBehaviourAroundIt(unittest.TestCase):
    def test_an_invalid_token_still_raises_401(self):
        with self.assertLogs(LOGGER, logging.WARNING):
            with self.assertRaises(HTTPException) as caught:
                get_current_user(_bearer("not.a.jwt"))

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.headers["WWW-Authenticate"], "Bearer")

    def test_an_absent_bearer_header_is_still_the_dev_fallback_and_is_not_logged(self):
        """Deliberately unlogged: the fallback answers most frontend traffic today, so a line
        per request would drown the rejections above. That it exists at all is KAN-61's."""
        with self.assertNoLogs(LOGGER, logging.DEBUG):
            user = get_current_user(None)

        self.assertEqual(user["email"], "dev@local.host")


if __name__ == "__main__":
    unittest.main()
