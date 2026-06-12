from __future__ import annotations

import logging
import threading
import traceback
from pathlib import Path
from typing import Any

from tools.sync.config import is_enabled
from tools.sync.runner import run_sync

_LOCK = threading.Lock()
_IDLE = threading.Condition(_LOCK)
_RUNNING = False
_PENDING_REASONS: list[str] = []
_LAST_RESULT: dict[str, Any] | None = None
_LAST_ERROR: str | None = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = PROJECT_ROOT / "logs" / "openclaw" / "crm_sync.log"


def _log(message: str, logger: logging.Logger | None = None) -> None:
    if logger is not None:
        logger.info(message)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def _worker(initial_reasons: list[str], logger: logging.Logger | None) -> None:
    global _RUNNING, _LAST_ERROR, _LAST_RESULT
    reasons = initial_reasons
    while True:
        reason_text = ", ".join(reasons)
        try:
            _log(f"crm sync started: {reason_text}", logger)
            result = run_sync()
            with _LOCK:
                _LAST_RESULT = result
                _LAST_ERROR = None if result.get("ok") else str(result.get("error") or result)
            _log(f"crm sync finished: ok={bool(result.get('ok'))} reason={reason_text}", logger)
        except Exception:
            error = traceback.format_exc()
            with _LOCK:
                _LAST_ERROR = error
                _LAST_RESULT = {"ok": False, "error": error}
            _log(f"crm sync failed: {error}", logger)

        with _LOCK:
            if _PENDING_REASONS:
                reasons = list(_PENDING_REASONS)
                _PENDING_REASONS.clear()
                continue
            _RUNNING = False
            _IDLE.notify_all()
            return


def trigger_crm_sync(reason: str, *, logger: logging.Logger | None = None) -> dict[str, Any]:
    if not is_enabled():
        return {"ok": True, "started": False, "disabled": True, "reason": reason}

    clean_reason = str(reason or "unspecified").strip() or "unspecified"
    with _LOCK:
        global _RUNNING
        if _RUNNING:
            _PENDING_REASONS.append(clean_reason)
            return {"ok": True, "started": False, "queued": True, "reason": clean_reason}
        _RUNNING = True
        thread = threading.Thread(target=_worker, args=([clean_reason], logger), daemon=True)
        thread.start()
        return {"ok": True, "started": True, "reason": clean_reason}


def wait_for_idle(timeout: float | None = None) -> bool:
    with _LOCK:
        if not _RUNNING:
            return True
        return _IDLE.wait_for(lambda: not _RUNNING, timeout=timeout)


def last_status() -> dict[str, Any]:
    with _LOCK:
        return {
            "running": _RUNNING,
            "pending": list(_PENDING_REASONS),
            "last_result": _LAST_RESULT,
            "last_error": _LAST_ERROR,
        }
