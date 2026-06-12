from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.sync.media_uploader import FakeMediaUploader, file_sha256
from tools.sync.models import AssetMedia


class MediaUploaderTests(unittest.TestCase):
    def test_fake_uploader_uses_actual_file_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.jpg"
            path.write_bytes(b"actual bytes")
            media = AssetMedia(
                asset_id="asset1",
                source_kind="travel_index",
                source_path="local/path.jpg",
                file_path=path,
            )

            result = FakeMediaUploader().upload(media)

            sha = file_sha256(path)
            self.assertEqual(result.sha256, sha)
            self.assertEqual(result.media_id, f"{sha}.jpg")
            self.assertTrue(result.url.endswith(f"{sha}.jpg"))


if __name__ == "__main__":
    unittest.main()
