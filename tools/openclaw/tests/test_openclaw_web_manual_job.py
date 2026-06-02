import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_MODULE_PATH = PROJECT_ROOT / "travel-agent-interface" / "openclaw_web.py"


spec = importlib.util.spec_from_file_location("openclaw_web_for_tests", WEB_MODULE_PATH)
openclaw_web = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(openclaw_web)


class ManualJobSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.original_manual_job = dict(openclaw_web.MANUAL_JOB)

    def tearDown(self):
        openclaw_web.MANUAL_JOB.clear()
        openclaw_web.MANUAL_JOB.update(self.original_manual_job)

    def test_running_manual_job_is_not_overwritten_by_previous_latest_job(self):
        openclaw_web.MANUAL_JOB.update(
            {
                "running": True,
                "pid": 200,
                "status": "running",
                "trigger_source": "manual",
                "last_started_at": "2026-05-18T06:10:00Z",
                "last_finished_at": None,
                "last_success": None,
                "returncode": None,
            }
        )
        previous_latest = {
            "trigger_source": "manual",
            "status": "success",
            "running": False,
            "pid": 100,
            "started_at": "2026-05-18T06:00:00Z",
            "finished_at": "2026-05-18T06:01:00Z",
            "returncode": 0,
        }

        with patch.object(openclaw_web, "_latest_job_snapshot", return_value=previous_latest):
            snapshot = openclaw_web._manual_job_snapshot()

        self.assertTrue(snapshot["running"])
        self.assertEqual(snapshot["pid"], 200)
        self.assertEqual(snapshot["status"], "running")
        self.assertIsNone(snapshot["last_finished_at"])

    def test_running_manual_job_accepts_matching_latest_job_completion(self):
        openclaw_web.MANUAL_JOB.update(
            {
                "running": True,
                "pid": 200,
                "status": "running",
                "trigger_source": "manual",
                "last_started_at": "2026-05-18T06:10:00Z",
                "last_finished_at": None,
                "last_success": None,
                "returncode": None,
            }
        )
        matching_latest = {
            "trigger_source": "manual",
            "status": "success",
            "running": False,
            "pid": 200,
            "started_at": "2026-05-18T06:10:00Z",
            "finished_at": "2026-05-18T06:11:00Z",
            "returncode": 0,
        }

        with patch.object(openclaw_web, "_latest_job_snapshot", return_value=matching_latest):
            snapshot = openclaw_web._manual_job_snapshot()

        self.assertFalse(snapshot["running"])
        self.assertEqual(snapshot["pid"], 200)
        self.assertEqual(snapshot["status"], "success")
        self.assertEqual(snapshot["last_finished_at"], "2026-05-18T06:11:00Z")
        self.assertTrue(snapshot["last_success"])


class WatchManualProcessDrainTests(unittest.TestCase):
    """A finished RPA run must drain the pending-upload queue (it released the
    shared lock), otherwise an upload queued during the run is stranded."""

    def test_finished_run_drains_pending_upload_queue(self):
        class _FakeProc:
            def wait(self):
                return 0

        with patch.object(openclaw_web, "_set_manual_job"), \
                patch.object(openclaw_web, "_latest_job_snapshot", return_value=None), \
                patch.object(openclaw_web, "_prewarm_latest_thumbnails"), \
                patch.object(openclaw_web, "_start_pending_upload_pipeline_if_idle") as drain:
            openclaw_web._watch_manual_process(_FakeProc())

        drain.assert_called_once()

    def test_drains_even_when_watch_body_raises(self):
        class _FakeProc:
            def wait(self):
                raise RuntimeError("boom")

        with patch.object(openclaw_web, "_set_manual_job"), \
                patch.object(openclaw_web, "_start_pending_upload_pipeline_if_idle") as drain:
            openclaw_web._watch_manual_process(_FakeProc())

        drain.assert_called_once()


if __name__ == "__main__":
    unittest.main()
