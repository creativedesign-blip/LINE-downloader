import importlib.util
import io
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_MODULE_PATH = PROJECT_ROOT / "travel-agent-interface" / "openclaw_web.py"


spec = importlib.util.spec_from_file_location("openclaw_web_for_security_tests", WEB_MODULE_PATH)
openclaw_web = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(openclaw_web)


class FakeCsrfHandler:
    def __init__(self, headers: dict):
        self.headers = headers


class FakeBodyHandler:
    def __init__(self, content_length: int, raw: bytes = b"{}"):
        self.headers = {"Content-Length": str(content_length)}
        self.rfile = io.BytesIO(raw)
        self.close_connection = False


class FakeLoginHandler:
    def __init__(self, body: dict, ip: str):
        self.body = body
        self._ip = ip
        self.response = None

    def _client_ip(self):
        return self._ip

    def _read_json_body(self):
        return self.body

    def _json_auth_response(self, payload, status=HTTPStatus.OK, *, cookie=None):
        self.response = {"payload": payload, "status": status, "cookie": cookie}

    def _auth_cookie_header(self, token, *, max_age):
        return "openclaw_session=token"


class StaticAuthTests(unittest.TestCase):
    def test_spa_shell_and_assets_are_public(self):
        for path in ("/", "/index.html", "/favicon.ico", "/assets/index-abc.js", "/assets/x.css"):
            self.assertTrue(openclaw_web.Handler._static_path_is_public(path), path)

    def test_source_and_other_files_require_auth(self):
        for path in ("/openclaw_web.py", "/package.json", "/vite.config.js", "/secret.txt", "/logs/x"):
            self.assertFalse(openclaw_web.Handler._static_path_is_public(path), path)


class CsrfTests(unittest.TestCase):
    def _ok(self, headers):
        return openclaw_web.Handler._csrf_ok(FakeCsrfHandler(headers))

    def test_no_origin_is_allowed(self):
        self.assertTrue(self._ok({"Host": "travel.quick-buyer.com"}))

    def test_same_origin_is_allowed(self):
        self.assertTrue(self._ok({
            "Origin": "https://travel.quick-buyer.com",
            "Host": "travel.quick-buyer.com",
        }))

    def test_same_origin_localhost_with_port(self):
        self.assertTrue(self._ok({
            "Origin": "http://127.0.0.1:4173",
            "Host": "127.0.0.1:4173",
        }))

    def test_cross_origin_is_blocked(self):
        self.assertFalse(self._ok({
            "Origin": "https://evil.example",
            "Host": "travel.quick-buyer.com",
        }))


class JsonBodyCapTests(unittest.TestCase):
    def test_oversized_body_is_refused_without_reading(self):
        handler = FakeBodyHandler(openclaw_web.MAX_JSON_BODY_BYTES + 1, raw=b"x" * 10)
        with self.assertRaises(ValueError):
            openclaw_web.Handler._read_json_body(handler)
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.rfile.tell(), 0)  # body was never read

    def test_normal_body_is_parsed(self):
        raw = b'{"hello": "world"}'
        handler = FakeBodyHandler(len(raw), raw=raw)
        self.assertEqual(openclaw_web.Handler._read_json_body(handler), {"hello": "world"})

    def test_non_dict_body_coerced_to_empty(self):
        raw = b"[1, 2, 3]"
        handler = FakeBodyHandler(len(raw), raw=raw)
        self.assertEqual(openclaw_web.Handler._read_json_body(handler), {})


class LoginRateLimitTests(unittest.TestCase):
    def setUp(self):
        openclaw_web._LOGIN_FAILURES.clear()
        self.addCleanup(openclaw_web._LOGIN_FAILURES.clear)

    def test_repeated_failures_trigger_429(self):
        ip = "203.0.113.7"
        with patch.object(openclaw_web, "AUTH_CONFIGURED", True), \
             patch.object(openclaw_web, "AUTH_USERNAME", "admin"), \
             patch.object(openclaw_web, "AUTH_PASSWORD", "correct-horse"):
            # The first LOGIN_MAX_FAILURES bad attempts are answered 401...
            for _ in range(openclaw_web.LOGIN_MAX_FAILURES):
                handler = FakeLoginHandler({"username": "admin", "password": "wrong"}, ip)
                openclaw_web.Handler._handle_auth_login(handler)
                self.assertEqual(handler.response["status"], HTTPStatus.UNAUTHORIZED)
            # ...the next one is throttled.
            blocked = FakeLoginHandler({"username": "admin", "password": "wrong"}, ip)
            openclaw_web.Handler._handle_auth_login(blocked)
            self.assertEqual(blocked.response["status"], HTTPStatus.TOO_MANY_REQUESTS)
            self.assertGreater(blocked.response["payload"]["retry_after"], 0)

    def test_successful_login_clears_failures(self):
        ip = "203.0.113.8"
        with patch.object(openclaw_web, "AUTH_CONFIGURED", True), \
             patch.object(openclaw_web, "AUTH_USERNAME", "admin"), \
             patch.object(openclaw_web, "AUTH_PASSWORD", "correct-horse"):
            for _ in range(openclaw_web.LOGIN_MAX_FAILURES - 1):
                handler = FakeLoginHandler({"username": "admin", "password": "wrong"}, ip)
                openclaw_web.Handler._handle_auth_login(handler)
            ok = FakeLoginHandler({"username": "admin", "password": "correct-horse"}, ip)
            openclaw_web.Handler._handle_auth_login(ok)
            self.assertEqual(ok.response["status"], HTTPStatus.OK)
            self.assertNotIn(ip, openclaw_web._LOGIN_FAILURES)


class FakeCookieHandler:
    def __init__(self, secure_request: bool):
        self._secure = secure_request

    def _is_secure_request(self):
        return self._secure


class SecureCookieTests(unittest.TestCase):
    def _has_secure(self, *, force, secure_request):
        with patch.object(openclaw_web, "FORCE_SECURE_COOKIES", force):
            header = openclaw_web.Handler._auth_cookie_header(
                FakeCookieHandler(secure_request), "tok", max_age=100
            )
        return "Secure" in header.split("; ")

    def test_force_flag_sets_secure_even_without_https_header(self):
        self.assertTrue(self._has_secure(force=True, secure_request=False))

    def test_https_request_sets_secure(self):
        self.assertTrue(self._has_secure(force=False, secure_request=True))

    def test_plain_http_without_force_omits_secure(self):
        self.assertFalse(self._has_secure(force=False, secure_request=False))


class FakeJsonHandler:
    def __init__(self):
        self.json_calls = []

    def _json(self, payload, status=HTTPStatus.OK):
        self.json_calls.append((payload, status))


class DownloadCapTests(unittest.TestCase):
    def test_too_many_files_rejected(self):
        handler = FakeJsonHandler()
        files = [Path("nonexistent.jpg")] * (openclaw_web.MAX_DOWNLOAD_FILE_COUNT + 1)
        openclaw_web.Handler._send_download_zip(handler, files)
        self.assertEqual(handler.json_calls[-1][1], HTTPStatus.BAD_REQUEST)

    def test_empty_files_rejected(self):
        handler = FakeJsonHandler()
        openclaw_web.Handler._send_download_zip(handler, [])
        self.assertEqual(handler.json_calls[-1][1], HTTPStatus.BAD_REQUEST)


class DecompressionBombTests(unittest.TestCase):
    def _png(self, w, h):
        buf = io.BytesIO()
        openclaw_web.Image.new("RGB", (w, h)).save(buf, format="PNG")
        return buf.getvalue()

    def test_oversized_dimensions_rejected(self):
        err = openclaw_web._validate_upload_image_dimensions(
            self._png(openclaw_web.MAX_UPLOAD_IMAGE_EDGE_PX + 100, 8)
        )
        self.assertIsNotNone(err)
        self.assertIn("過大", err)

    def test_normal_image_passes_dimension_guard(self):
        self.assertIsNone(openclaw_web._validate_upload_image_dimensions(self._png(800, 600)))


class ItemDetailContainmentTests(unittest.TestCase):
    def setUp(self):
        import gc
        import shutil
        from tools.indexing.index_db import TravelIndex
        self._TravelIndex = TravelIndex
        self.tmp = Path(tempfile.mkdtemp(dir=str(PROJECT_ROOT)))

        def _cleanup():
            gc.collect()  # drop lingering sqlite connections so Windows can unlink
            shutil.rmtree(self.tmp, ignore_errors=True)

        self.addCleanup(_cleanup)
        self.db_path = self.tmp / "idx.db"
        with TravelIndex(self.db_path):
            pass  # create an empty index
        patcher = patch.object(openclaw_web, "DEFAULT_DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_sidecar(self):
        p = self.tmp / "x.jpg.json"
        p.write_text('{"source": {}}', encoding="utf-8")
        return p.relative_to(PROJECT_ROOT).as_posix()

    def test_unindexed_sidecar_is_refused(self):
        rel = self._make_sidecar()
        self.assertIsNone(openclaw_web._line_item_detail(rel))

    def test_indexed_sidecar_is_served(self):
        rel = self._make_sidecar()
        with self._TravelIndex(self.db_path) as idx:
            idx.upsert(sidecar_path=rel, image_path=rel[:-5])
        detail = openclaw_web._line_item_detail(rel)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["sidecar_path"], rel)


if __name__ == "__main__":
    unittest.main()
