from __future__ import annotations

import tempfile
import unittest
import sqlite3
from contextlib import closing
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

    def test_search_index_queries_uploaded_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder(
                "希臘促銷",
                folder_slug="upload_test_search",
                db_path=db_path,
            )
            image_path = Path(tmp) / "aegean.jpg"
            image_path.write_bytes(b"image")
            image = upload_catalog.add_image(folder["id"], image_path, "aegean.jpg", db_path=db_path)

            upload_catalog.upsert_image_search_index(
                image["id"],
                folder_id=folder["id"],
                search_text="愛琴海 聖托里尼 雅典",
                raw_text="愛琴海雙島漫遊",
                countries=["希臘"],
                regions=["聖托里尼"],
                months=[9, 10],
                features=["愛琴海"],
                price_from=110900,
                duration_days=10,
                sidecar_path="line-rpa/download/upload_test/branded/aegean.jpg",
                image_path="line-rpa/download/upload_test/travel/aegean.jpg",
                branded_path="line-rpa/download/upload_test/branded/aegean.jpg",
                source_time=image["uploaded_at"],
                db_path=db_path,
            )

            rows = upload_catalog.query_image_search_index(
                query_text="愛琴海",
                countries=["希臘"],
                months=[9],
                limit=10,
                db_path=db_path,
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["group_name"], "希臘促銷")
            self.assertEqual(rows[0]["countries"], ["希臘"])
            self.assertEqual(rows[0]["months"], [9, 10])
            self.assertEqual(rows[0]["price_from"], 110900)

    def test_missing_search_index_image_ids_ignores_indexed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder("批次", folder_slug="upload_test_missing_index", db_path=db_path)
            image_path = Path(tmp) / "sample.jpg"
            image_path.write_bytes(b"image")
            image = upload_catalog.add_image(folder["id"], image_path, "sample.jpg", db_path=db_path)

            self.assertEqual(upload_catalog.missing_search_index_image_ids(db_path=db_path), [image["id"]])

            upload_catalog.upsert_image_search_index(
                image["id"],
                folder_id=folder["id"],
                search_text="sample",
                db_path=db_path,
            )

            self.assertEqual(upload_catalog.missing_search_index_image_ids(db_path=db_path), [])

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

    def test_archive_folder_hides_from_default_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder("Korea promo", folder_slug="upload_test_archive_folder", db_path=db_path)

            archived = upload_catalog.archive_folder(folder["id"], db_path=db_path)

            self.assertIsNotNone(archived)
            self.assertIsNotNone(archived["archived_at"])
            self.assertIsNotNone(archived["delete_after"])
            self.assertIsNone(upload_catalog.get_folder(folder["id"], db_path=db_path))
            self.assertIsNotNone(upload_catalog.get_folder(folder["id"], include_archived=True, db_path=db_path))
            self.assertEqual(upload_catalog.list_folders(db_path=db_path), [])
            self.assertEqual(len(upload_catalog.list_folders(include_archived=True, db_path=db_path)), 1)

    def test_init_db_migrates_existing_folder_table_before_indexing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    """
                    CREATE TABLE upload_folders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        folder_slug TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        source TEXT NOT NULL DEFAULT 'upload',
                        status TEXT NOT NULL DEFAULT 'pending',
                        current_step TEXT NOT NULL DEFAULT 'upload',
                        step_statuses TEXT NOT NULL DEFAULT '{}',
                        image_count INTEGER NOT NULL DEFAULT 0,
                        line_groups TEXT NOT NULL DEFAULT '[]',
                        captured_at TEXT,
                        job_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()

            folder = upload_catalog.create_folder("Legacy", folder_slug="upload_test_legacy", db_path=db_path)

            self.assertIn("archived_at", folder)
            self.assertIsNone(folder["archived_at"])

    def test_purge_expired_archived_folders_removes_db_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder("Expired", folder_slug="upload_test_expired", db_path=db_path)
            upload_catalog.archive_folder(folder["id"], db_path=db_path)
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "UPDATE upload_folders SET delete_after = ? WHERE id = ?",
                    ("2026-05-01T00:00:00Z", folder["id"]),
                )
                conn.commit()

            result = upload_catalog.purge_expired_archived_folders(
                now="2026-05-02T00:00:00Z",
                delete_files=False,
                db_path=db_path,
            )

            self.assertEqual(result["deleted"], [folder["id"]])
            self.assertEqual(result["errors"], [])
            self.assertIsNone(upload_catalog.get_folder(folder["id"], include_archived=True, db_path=db_path))

    def test_list_images_filters_uploaded_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "catalog.db"
            folder = upload_catalog.create_folder("Korea promo", folder_slug="upload_test_time_filter", db_path=db_path)
            first_path = Path(tmp) / "first.jpg"
            second_path = Path(tmp) / "second.jpg"
            first_path.write_bytes(b"first")
            second_path.write_bytes(b"second")
            first = upload_catalog.add_image(folder["id"], first_path, "first.jpg", db_path=db_path)
            second = upload_catalog.add_image(folder["id"], second_path, "second.jpg", db_path=db_path)
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute("UPDATE uploaded_images SET uploaded_at = ? WHERE id = ?", ("2026-05-18T00:00:00Z", first["id"]))
                conn.execute("UPDATE uploaded_images SET uploaded_at = ? WHERE id = ?", ("2026-05-19T00:00:00Z", second["id"]))
                conn.commit()

            images = upload_catalog.list_images(
                folder["id"],
                uploaded_from="2026-05-19T00:00:00Z",
                db_path=db_path,
            )

            self.assertEqual([image["id"] for image in images], [second["id"]])

            images = upload_catalog.list_images(
                folder["id"],
                uploaded_to="2026-05-18T23:59:59Z",
                db_path=db_path,
            )

            self.assertEqual([image["id"] for image in images], [first["id"]])

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
