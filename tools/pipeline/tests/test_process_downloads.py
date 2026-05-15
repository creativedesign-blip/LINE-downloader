from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.common.targets import DOWNLOADS_DIR, load_target_ids
from tools.indexing.reindex import collect_travel_sidecars
from tools.pipeline.process_downloads import (
    build_commands,
    collect_review_images,
    discover_target_ids,
    load_image_index,
    sync_image_index_for_targets,
)


TEST_TARGET = "pipeline_test_target"


def make_args(**overrides):
    defaults = {
        "python": "python",
        "skip_ocr": False,
        "skip_branding": False,
        "skip_index": False,
        "skip_ocr_enrich": False,
        "force_branding": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestPipelineTargetDiscovery(unittest.TestCase):
    def setUp(self):
        self.target_dir = DOWNLOADS_DIR / TEST_TARGET
        self.inbox_dir = self.target_dir / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.target_dir, ignore_errors=True)

    def test_load_target_ids_discovers_download_folders(self):
        self.assertIn(TEST_TARGET, load_target_ids())
        self.assertEqual(discover_target_ids(TEST_TARGET), [TEST_TARGET])

    def test_load_target_ids_ignores_internal_download_folders(self):
        internal_dir = DOWNLOADS_DIR / "_internal_pipeline_test"
        internal_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.assertNotIn(internal_dir.name, load_target_ids())
        finally:
            shutil.rmtree(internal_dir, ignore_errors=True)

    def test_build_commands_uses_root_pending_images(self):
        (self.target_dir / "sample.jpg").write_bytes(b"not-a-real-image")
        commands = build_commands(make_args(), [TEST_TARGET])
        ocr_commands = [command for name, command in commands if name == "ocr:all"]
        self.assertEqual(len(ocr_commands), 1)
        self.assertIn("--target", ocr_commands[0])
        self.assertIn(TEST_TARGET, ocr_commands[0])

        names = [name for name, _ in commands]
        self.assertIn("branding:all", names)
        self.assertIn("index:all", names)

    def test_build_commands_also_supports_inbox_pending_images(self):
        (self.inbox_dir / "sample.jpg").write_bytes(b"not-a-real-image")
        commands = build_commands(make_args(), [TEST_TARGET])
        names = [name for name, _ in commands]
        self.assertIn("ocr:all", names)
        self.assertIn("branding:all", names)
        self.assertIn("index:all", names)

    def test_skip_ocr_still_brands_and_indexes(self):
        commands = build_commands(make_args(skip_ocr=True), [TEST_TARGET])
        names = [name for name, _ in commands]
        self.assertNotIn("ocr:all", names)
        self.assertIn("branding:all", names)
        self.assertIn("index:all", names)

    def test_indexing_collects_non_jpg_sidecars(self):
        travel_dir = self.target_dir / "travel"
        travel_dir.mkdir(parents=True, exist_ok=True)
        (travel_dir / "sample.png").write_bytes(b"not-a-real-image")
        (travel_dir / "sample.png.json").write_text("{}", encoding="utf-8")
        sidecars = collect_travel_sidecars([TEST_TARGET])
        self.assertIn(travel_dir / "sample.png.json", sidecars)

    def test_sync_image_index_uses_classified_original_folders_only(self):
        travel_dir = self.target_dir / "travel"
        other_dir = self.target_dir / "other"
        review_dir = self.target_dir / "review"
        branded_dir = self.target_dir / "branded"
        for folder in (travel_dir, other_dir, review_dir, branded_dir):
            folder.mkdir(parents=True, exist_ok=True)
        (travel_dir / "a.jpg").write_bytes(b"travel")
        (other_dir / "b.png").write_bytes(b"other")
        (review_dir / "c.webp").write_bytes(b"review")
        (branded_dir / "d.jpg").write_bytes(b"branded-should-not-count")

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "image_index.json"
            cache_path = Path(tmp) / "cache.json"
            step = sync_image_index_for_targets(
                [TEST_TARGET], index_path=index_path, cache_path=cache_path,
            )

            self.assertEqual(step.exit_code, 0)
            self.assertIn("--cache-misses", step.command)
            misses = step.command[step.command.index("--cache-misses") + 1]
            self.assertEqual(misses, "3")  # cold run: hash all 3 images

            index = load_image_index(index_path)
            self.assertEqual(len(index[TEST_TARGET]), 3)
            self.assertTrue(cache_path.exists())

    def test_sync_image_index_reuses_hash_cache_on_unchanged_files(self):
        travel_dir = self.target_dir / "travel"
        travel_dir.mkdir(parents=True, exist_ok=True)
        (travel_dir / "a.jpg").write_bytes(b"travel")
        (travel_dir / "b.jpg").write_bytes(b"another")

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "image_index.json"
            cache_path = Path(tmp) / "cache.json"

            sync_image_index_for_targets(
                [TEST_TARGET], index_path=index_path, cache_path=cache_path,
            )
            # Second run: nothing changed, every file should hit the cache.
            step = sync_image_index_for_targets(
                [TEST_TARGET], index_path=index_path, cache_path=cache_path,
            )

            misses = step.command[step.command.index("--cache-misses") + 1]
            hits = step.command[step.command.index("--cache-hits") + 1]
            self.assertEqual(misses, "0")
            self.assertEqual(hits, "2")

    def test_sync_image_index_drops_cache_entry_when_file_deleted(self):
        travel_dir = self.target_dir / "travel"
        travel_dir.mkdir(parents=True, exist_ok=True)
        keep = travel_dir / "keep.jpg"
        gone = travel_dir / "gone.jpg"
        keep.write_bytes(b"keep")
        gone.write_bytes(b"gone")

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "image_index.json"
            cache_path = Path(tmp) / "cache.json"

            sync_image_index_for_targets(
                [TEST_TARGET], index_path=index_path, cache_path=cache_path,
            )
            gone.unlink()
            sync_image_index_for_targets(
                [TEST_TARGET], index_path=index_path, cache_path=cache_path,
            )

            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            kept_paths = [p for p in cache if p.endswith("keep.jpg")]
            gone_paths = [p for p in cache if p.endswith("gone.jpg")]
            self.assertEqual(len(kept_paths), 1)
            self.assertEqual(len(gone_paths), 0)

    def test_collect_review_images_lists_review_folder_only(self):
        review_dir = self.target_dir / "review"
        other_dir = self.target_dir / "other"
        review_dir.mkdir(parents=True, exist_ok=True)
        other_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "needs-check.jpg").write_bytes(b"review")
        (review_dir / "needs-check.jpg.json").write_text("{}", encoding="utf-8")
        (other_dir / "not-review.jpg").write_bytes(b"other")

        review = collect_review_images([TEST_TARGET])

        self.assertEqual(
            review,
            {TEST_TARGET: [f"line-rpa/download/{TEST_TARGET}/review/needs-check.jpg"]},
        )


if __name__ == "__main__":
    unittest.main()
