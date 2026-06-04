import importlib.util
import io
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_MODULE_PATH = PROJECT_ROOT / "travel-agent-interface" / "openclaw_web.py"


spec = importlib.util.spec_from_file_location("openclaw_web_for_media_tests", WEB_MODULE_PATH)
openclaw_web = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(openclaw_web)


class FakeMediaHandler:
    """Minimal stand-in capturing what _handle_media sends."""

    def __init__(self):
        self.error = None
        self.status = None
        self.sent_headers = {}
        self.wfile = io.BytesIO()
        self.ended = False

    def send_error(self, status, message=None):
        self.error = (status, message)

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        self.ended = True


class MediaAccessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=str(PROJECT_ROOT))
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)

    def _rel(self, path: Path) -> str:
        return path.relative_to(PROJECT_ROOT).as_posix()

    def _call(self, raw_path: str) -> FakeMediaHandler:
        handler = FakeMediaHandler()
        openclaw_web.Handler._handle_media(handler, {"path": [raw_path]})
        return handler

    def test_serves_image_file(self):
        img = self.tmpdir / "ok.png"
        payload = b"\x89PNG\r\n\x1a\nfake-pixels"
        img.write_bytes(payload)

        handler = self._call(self._rel(img))

        self.assertIsNone(handler.error)
        self.assertEqual(handler.status, HTTPStatus.OK)
        self.assertEqual(handler.wfile.getvalue(), payload)

    def test_rejects_non_image_files(self):
        # The critical bleed: /media must never serve the HMAC session secret,
        # the SQLite catalogs, or source under PROJECT_ROOT.
        cases = {
            "auth_secret.bin": b"\x00" * 32,
            "upload_catalog.db": b"SQLite format 3\x00",
            "module.py": b"print('secret')",
            "settings.json": b"{}",
            "run.ps1": b"Write-Host hi",
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                victim = self.tmpdir / name
                victim.write_bytes(data)
                handler = self._call(self._rel(victim))
                self.assertIsNotNone(handler.error, name)
                self.assertEqual(handler.error[0], HTTPStatus.FORBIDDEN, name)
                self.assertEqual(handler.wfile.getvalue(), b"", name)

    def test_path_outside_project_is_forbidden(self):
        handler = self._call("../../../../../Windows/win.ini")

        self.assertIsNotNone(handler.error)
        self.assertEqual(handler.error[0], HTTPStatus.FORBIDDEN)
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_null_byte_path_does_not_crash(self):
        # %00 decodes to an embedded null byte; _resolve_project_file must return
        # None instead of letting Path.resolve() raise an unhandled 500.
        self.assertIsNone(openclaw_web._resolve_project_file("foo\x00.png"))


if __name__ == "__main__":
    unittest.main()
