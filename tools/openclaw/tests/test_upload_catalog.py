from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.openclaw import upload_catalog


class UploadCatalogTests(unittest.TestCase):
    def test_create_folder_and_manual_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder(
                "東京五月促銷",
                "重要素材",
                folder_slug="upload_test_tokyo",
                db_path=db_path,
            )
            self.assertEqual(folder["display_name"], "東京五月促銷")
            self.assertEqual(folder["note"], "重要素材")
            self.assertEqual(folder["status"], "pending")

            image_path = Path(tmp) / "sample.jpg"
            image_path.write_bytes(b"image")
            image = upload_catalog.add_image(folder["id"], image_path, "sample.jpg", db_path=db_path)
            tag = upload_catalog.add_manual_tag(image["id"], "主打", note="首頁", db_path=db_path)

            images = upload_catalog.list_images(folder["id"], db_path=db_path)
            tags = upload_catalog.list_manual_tags(image["id"], db_path=db_path)

            self.assertEqual(len(images), 1)
            self.assertEqual(tags[0]["id"], tag["id"])
            self.assertEqual(tags[0]["tag"], "主打")

    def test_update_image_metadata_and_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder("批次", folder_slug="upload_test_meta", db_path=db_path)
            image_path = Path(tmp) / "sample.jpg"
            image_path.write_bytes(b"image")
            image = upload_catalog.add_image(folder["id"], image_path, "sample.jpg", db_path=db_path)

            updated = upload_catalog.update_image_metadata(
                image["id"],
                display_name="首頁主圖",
                ocr_tags_override=["日本", "促銷"],
                reference_text="LINE 原文",
                manual_note="買一送一",
                db_path=db_path,
            )

            self.assertEqual(updated["display_name"], "首頁主圖")
            self.assertEqual(updated["ocr_tags_override"], ["日本", "促銷"])
            self.assertEqual(updated["reference_text"], "LINE 原文")
            self.assertEqual(updated["manual_note"], "買一送一")

            self.assertTrue(upload_catalog.archive_image(image["id"], db_path=db_path))
            self.assertEqual(upload_catalog.list_images(folder["id"], db_path=db_path), [])

    def test_update_folder_status_merges_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder(
                "批次",
                folder_slug="upload_test_batch",
                db_path=db_path,
            )

            upload_catalog.update_folder_status(
                folder["id"],
                status="running",
                current_step="ocr",
                step_statuses={"upload": "success"},
                db_path=db_path,
            )
            updated = upload_catalog.update_folder_status(
                folder["id"],
                current_step="compose",
                step_statuses={"ocr": "success"},
                db_path=db_path,
            )

            self.assertEqual(updated["status"], "running")
            self.assertEqual(updated["current_step"], "compose")
            self.assertEqual(updated["step_statuses"]["upload"], "success")
            self.assertEqual(updated["step_statuses"]["ocr"], "success")

    def test_line_folder_slug_contains_groups_and_timestamp(self):
        slug = upload_catalog.line_folder_slug(["LINE/群組A", "群組 B", "群組C"], "20260518_160000")

        self.assertTrue(slug.startswith("line_auto_20260518_160000_"))
        self.assertIn("LINE", slug)
        self.assertIn("plus1", slug)


    def test_stored_path_registry_keeps_deleted_file_reserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder("?寞活", folder_slug="upload_test_reserved", db_path=db_path)
            image_path = Path(tmp) / "0001_sample.jpg"
            image_path.write_bytes(b"image")

            upload_catalog.add_image(folder["id"], image_path, "sample.jpg", db_path=db_path)
            image_path.unlink()

            self.assertTrue(upload_catalog.stored_path_is_registered(image_path, db_path=db_path))
            self.assertFalse(upload_catalog.stored_path_is_registered(Path(tmp) / "0002_sample.jpg", db_path=db_path))


if __name__ == "__main__":
    unittest.main()
