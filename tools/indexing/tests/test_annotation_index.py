from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tools.common.db import open_db
from tools.indexing.annotation_index import rebuild_image_annotations
from tools.openclaw import upload_catalog


class TestAnnotationIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.catalog = self.tmp / "upload_catalog.db"
        self.travel = self.tmp / "travel_index.db"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_catalog(self):
        conn = upload_catalog.connect(self.catalog)
        try:
            conn.execute(
                "INSERT INTO upload_folders (folder_slug, display_name, created_at, updated_at) "
                "VALUES ('f1', 'F1', 't', 't')"
            )
            folder_id = conn.execute("SELECT id FROM upload_folders WHERE folder_slug='f1'").fetchone()[0]
            conn.execute(
                "INSERT INTO uploaded_images "
                "(folder_id, original_filename, stored_path, sha256, reference_text, uploaded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (folder_id, "trip.jpg", "x/trip.jpg", "sha-1", "VIP 客戶備註", "t"),
            )
            image_id = conn.execute("SELECT id FROM uploaded_images WHERE sha256='sha-1'").fetchone()[0]
            conn.execute(
                "INSERT INTO manual_tags (image_id, tag, created_at) VALUES (?, ?, ?)",
                (image_id, "親子團", "t"),
            )
            conn.commit()
            return image_id
        finally:
            conn.close()

    def test_rebuild_collects_annotations_by_sha(self):
        self._seed_catalog()
        result = rebuild_image_annotations(travel_db=self.travel, catalog_db=self.catalog)
        self.assertEqual(result["annotations"], 1)
        conn = open_db(self.travel)
        try:
            row = conn.execute(
                "SELECT search_text FROM image_annotations WHERE image_sha256='sha-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertIn("親子團", row[0])        # manual tag
        self.assertIn("VIP 客戶備註", row[0])   # reference_text
        self.assertIn("trip.jpg", row[0])        # original filename

    def test_rebuild_is_idempotent_and_replaces(self):
        self._seed_catalog()
        rebuild_image_annotations(travel_db=self.travel, catalog_db=self.catalog)
        # Second run must not duplicate rows.
        rebuild_image_annotations(travel_db=self.travel, catalog_db=self.catalog)
        conn = open_db(self.travel)
        try:
            count = conn.execute("SELECT COUNT(*) FROM image_annotations").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_archived_image_is_excluded(self):
        self._seed_catalog()
        conn = open_db(self.catalog)
        try:
            conn.execute("UPDATE uploaded_images SET archived_at='t' WHERE sha256='sha-1'")
            conn.commit()
        finally:
            conn.close()
        result = rebuild_image_annotations(travel_db=self.travel, catalog_db=self.catalog)
        self.assertEqual(result["annotations"], 0)


if __name__ == "__main__":
    unittest.main()
