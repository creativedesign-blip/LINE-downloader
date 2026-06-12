from __future__ import annotations

import socket
import subprocess
import time

from tools.sync.config import SyncConfig


class SSHTunnel:
    def __init__(self, config: SyncConfig):
        self.config = config
        self.process: subprocess.Popen | None = None

    def __enter__(self) -> "SSHTunnel":
        args = [
            "ssh",
            "-F",
            "NUL",
            "-i",
            self.config.ssh_key,
            "-N",
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-p",
            str(self.config.ssh_port),
            "-L",
            (
                f"{self.config.local_port}:{self.config.mysql_remote_host}:"
                f"{self.config.mysql_remote_port}"
            ),
            f"{self.config.ssh_user}@{self.config.ssh_host}",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(args, creationflags=creationflags)
        _wait_for_port("127.0.0.1", self.config.local_port, self.process)
        return self

    def __exit__(self, *exc: object) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def _wait_for_port(host: str, port: int, process: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"ssh tunnel exited with code {process.returncode}")
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for tunnel port {host}:{port}")
