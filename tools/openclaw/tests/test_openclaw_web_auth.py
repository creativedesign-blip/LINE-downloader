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
    def __init__(self, body: dict):
        self.body = body
        self.response = None

    def _client_ip(self):
        return "test-client"

    def _read_json_body(self):
        return self.body

    def _json_auth_response(self, payload, status=HTTPStatus.OK, *, cookie=None):
        self.response = {"payload": payload, "status": status, "cookie": cookie}

    def _auth_cookie_header(self, token, *, max_age):
        return f"openclaw_session={token}; Max-Age={max_age}"


class AuthEnvironmentTests(unittest.TestCase):
    def test_login_is_rejected_when_auth_env_is_missing(self):
        handler = FakeAuthHandler({"username": "admin_dadova", "password": "StarBit123"})

        with patch.object(openclaw_web, "AUTH_CONFIGURED", False):
            openclaw_web.Handler._handle_auth_login(handler)

        self.assertEqual(handler.response["status"], HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertFalse(handler.response["payload"]["ok"])

    def test_login_uses_credentials_from_environment(self):
        handler = FakeAuthHandler({"username": "admin_dadova", "password": "StarBit123"})

        with patch.object(openclaw_web, "AUTH_CONFIGURED", True), \
             patch.object(openclaw_web, "AUTH_USERNAME", "admin_dadova"), \
             patch.object(openclaw_web, "AUTH_PASSWORD", "StarBit123"):
            openclaw_web.Handler._handle_auth_login(handler)

        self.assertEqual(handler.response["status"], HTTPStatus.OK)
        self.assertTrue(handler.response["payload"]["ok"])
        self.assertEqual(handler.response["payload"]["username"], "admin_dadova")

    def test_main_fails_when_auth_env_is_missing(self):
        with patch.object(openclaw_web, "AUTH_CONFIGURED", False), \
             patch.object(openclaw_web, "_configure_logging"):
            self.assertEqual(openclaw_web.main(), 1)


if __name__ == "__main__":
    unittest.main()
