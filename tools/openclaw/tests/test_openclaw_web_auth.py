import importlib.util
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_MODULE_PATH = PROJECT_ROOT / "travel-agent-interface" / "openclaw_web.py"


spec = importlib.util.spec_from_file_location("openclaw_web_for_auth_tests", WEB_MODULE_PATH)
openclaw_web = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(openclaw_web)


class FakeAuthHandler:
    def __init__(self, *, secure: bool, body: dict):
        self.secure = secure
        self.body = body
        self.response = None

    def _is_secure_request(self):
        return self.secure

    def _read_json_body(self):
        return self.body

    def _json_auth_response(self, payload, status=HTTPStatus.OK, *, cookie=None):
        self.response = {"payload": payload, "status": status, "cookie": cookie}

    def _auth_cookie_header(self, token, *, max_age):
        return f"openclaw_session={token}; Max-Age={max_age}"


class AuthLoginDefaultsTests(unittest.TestCase):
    def test_default_credentials_are_blocked_for_secure_proxy_login(self):
        handler = FakeAuthHandler(
            secure=True,
            body={
                "username": openclaw_web.DEFAULT_AUTH_USERNAME,
                "password": openclaw_web.DEFAULT_AUTH_PASSWORD,
            },
        )

        with patch.object(openclaw_web, "USING_DEFAULT_AUTH_CREDENTIALS", True):
            openclaw_web.Handler._handle_auth_login(handler)

        self.assertEqual(handler.response["status"], HTTPStatus.FORBIDDEN)
        self.assertFalse(handler.response["payload"]["ok"])

    def test_default_credentials_still_work_for_local_non_proxy_login(self):
        handler = FakeAuthHandler(
            secure=False,
            body={
                "username": openclaw_web.DEFAULT_AUTH_USERNAME,
                "password": openclaw_web.DEFAULT_AUTH_PASSWORD,
            },
        )

        with patch.object(openclaw_web, "USING_DEFAULT_AUTH_CREDENTIALS", True):
            openclaw_web.Handler._handle_auth_login(handler)

        self.assertEqual(handler.response["status"], HTTPStatus.OK)
        self.assertTrue(handler.response["payload"]["ok"])
        self.assertEqual(handler.response["payload"]["username"], openclaw_web.DEFAULT_AUTH_USERNAME)


if __name__ == "__main__":
    unittest.main()
