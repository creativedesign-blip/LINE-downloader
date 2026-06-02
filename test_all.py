"""Root-level unittest discovery bridge.

Some project tests live under non-package folders such as `line-rpa`, so plain
root discovery would otherwise run zero tests. The LINE RPA tests intentionally
patch process-global stdlib state, so each suite is executed in a subprocess to
keep test environments isolated.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class RepositoryTestSuites(unittest.TestCase):
    def _run_suite(self, name: str, command: list[str], *, cwd: Path = ROOT) -> None:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            self.fail(
                f"{name} failed with exit code {completed.returncode}\n"
                f"STDOUT:\n{completed.stdout}\n"
                f"STDERR:\n{completed.stderr}"
            )

    def test_tools_suite(self) -> None:
        self._run_suite(
            "tools unittest suite",
            [sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test*.py"],
        )

    def test_filter_suite(self) -> None:
        self._run_suite(
            "filter unittest suite",
            [sys.executable, "-m", "unittest", "discover", "-s", "filter", "-p", "test*.py"],
        )

    def test_line_rpa_suite(self) -> None:
        self._run_suite(
            "line-rpa unittest suite",
            [sys.executable, "-m", "unittest", "test_line_image_downloader.py"],
            cwd=ROOT / "line-rpa",
        )
