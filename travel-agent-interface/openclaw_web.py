from __future__ import annotations

import json
import base64
import hashlib
import hmac
import io
import logging
import math
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

logger = logging.getLogger("openclaw_web")

from PIL import Image, ImageOps

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover - optional runtime dependency
    OpenCC = None


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "dist" if (APP_DIR / "dist" / "index.html").is_file() else APP_DIR
PROJECT_ROOT = APP_DIR.parent
THUMBNAIL_DIR = PROJECT_ROOT / ".cache" / "openclaw-thumbnails"
CLIPBOARD_SCRIPT = PROJECT_ROOT / "tools" / "openclaw" / "copy_files_to_clipboard.ps1"
RUN_RPA_SCRIPT = PROJECT_ROOT / "tools" / "openclaw" / "run_scheduled_line_rpa.ps1"
RUN_UPLOAD_SCRIPT = PROJECT_ROOT / "tools" / "openclaw" / "run_uploaded_images.ps1"
LATEST_JOB_PATH = PROJECT_ROOT / "logs" / "openclaw" / "latest_job.json"
RUN_LOCK_PATH = PROJECT_ROOT / "logs" / "openclaw" / "line-rpa-scheduled.lock"
OPENCLAW_SETTINGS_PATH = PROJECT_ROOT / "logs" / "openclaw" / "settings.json"
PENDING_UPLOAD_JOBS_PATH = PROJECT_ROOT / "logs" / "openclaw" / "pending_upload_jobs.json"
CHAT_REQUEST_LOG_PATH = PROJECT_ROOT / "logs" / "openclaw" / "chat_requests.jsonl"
AUTH_SECRET_PATH = PROJECT_ROOT / "logs" / "openclaw" / "auth_secret.bin"
ITEM_ANNOTATIONS_PATH = PROJECT_ROOT / "logs" / "openclaw" / "item_annotations.json"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

JOB_LOCK = threading.Lock()
PENDING_UPLOAD_LOCK = threading.Lock()
ITEM_ANNOTATIONS_LOCK = threading.Lock()
MANUAL_JOB: dict[str, object] = {
    "running": False,
    "pid": None,
    "last_started_at": None,
    "last_finished_at": None,
    "last_success": None,
    "last_error": None,
    "returncode": None,
}
DEFAULT_AUTH_USERNAME = "admin_dadova"
DEFAULT_AUTH_PASSWORD = "StarBit123"
AUTH_USERNAME = os.environ.get("OPENCLAW_WEB_USER", DEFAULT_AUTH_USERNAME)
AUTH_PASSWORD = os.environ.get("OPENCLAW_WEB_PASSWORD", DEFAULT_AUTH_PASSWORD)
AUTH_COOKIE_NAME = "openclaw_session"
AUTH_SESSION_TTL_SECONDS = 12 * 60 * 60
AUTH_SESSION_TTL_REMEMBER_SECONDS = 30 * 24 * 60 * 60
_AUTH_SECRET_LOCK = threading.Lock()
_AUTH_SECRET_CACHE: bytes | None = None
SYSTEM_TAGS_CLEARED_SENTINEL = "__openclaw_system_tags_cleared__"
_OPENCC_T2TW = OpenCC("s2tw") if OpenCC else None
_OCR_TAG_FALLBACK_TRANSLATION = str.maketrans({
    "税": "稅",
    "国": "國",
    "团": "團",
    "东": "東",
    "万": "萬",
    "龙": "龍",
    "广": "廣",
    "门": "門",
    "乐": "樂",
    "发": "發",
    "台": "臺",
})
_PUNCTUATION_ONLY_TAG = re.compile(r"^[\s.。…·・,，、;；:：!?！？~～\-—_]+$")

from tools.common.db import open_db  # noqa: E402
from tools.openclaw.operations import (  # noqa: E402
    DEFAULT_DB_PATH,
    check_duplicates,
    processing_status,
    query_itineraries,
    query_latest_results,
    record_duplicate_review,
)
from tools.openclaw.upload_catalog import (  # noqa: E402
    CATALOG_DB_PATH,
    add_image,
    add_manual_tag,
    archive_image,
    archive_folder,
    create_folder,
    delete_manual_tag,
    delete_image_search_index,
    folder_target_path,
    get_folder,
    list_folders,
    list_images,
    list_manual_tags,
    missing_search_index_image_ids,
    query_image_search_index,
    safe_stored_filename,
    same_sha_image_ids,
    stored_path_is_registered,
    upsert_image_search_index,
    update_image_metadata,
    update_folder_status,
    update_manual_tag,
)
from tools.common.image_seen import file_sha256  # noqa: E402
from tools.indexing.extractor import (  # noqa: E402
    extract_country,
    extract_duration,
    extract_features,
    extract_months,
    extract_region,
)
from tools.indexing.number_parse import parse_price_bounds  # noqa: E402


def _first(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    return values[0] if values else default


def _json_list(value: object) -> list:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_object(value: object) -> dict:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_or_create_persistent_auth_secret() -> bytes:
    if AUTH_SECRET_PATH.is_file():
        try:
            existing = AUTH_SECRET_PATH.read_bytes()
        except OSError:
            existing = b""
        if len(existing) >= 32:
            return existing
    AUTH_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_secret = secrets.token_bytes(32)
    try:
        fd = os.open(str(AUTH_SECRET_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return AUTH_SECRET_PATH.read_bytes()
    try:
        os.write(fd, new_secret)
    finally:
        os.close(fd)
    return new_secret


def _auth_secret() -> bytes:
    global _AUTH_SECRET_CACHE
    if _AUTH_SECRET_CACHE is not None:
        return _AUTH_SECRET_CACHE
    with _AUTH_SECRET_LOCK:
        if _AUTH_SECRET_CACHE is not None:
            return _AUTH_SECRET_CACHE
        raw = os.environ.get("OPENCLAW_WEB_AUTH_SECRET")
        # Previous versions derived this from AUTH_USERNAME:AUTH_PASSWORD:PROJECT_ROOT,
        # which made the HMAC key trivially reproducible by anyone with repo access.
        # Random + persisted closes that forgery vector.
        secret = raw.encode("utf-8") if raw else _load_or_create_persistent_auth_secret()
        _AUTH_SECRET_CACHE = secret
        return secret


def _sign_auth_session(username: str, expires_at: int) -> str:
    body = f"{username}|{expires_at}".encode("utf-8")
    return hmac.new(_auth_secret(), body, hashlib.sha256).hexdigest()


def _encode_auth_session(username: str, ttl_seconds: int = AUTH_SESSION_TTL_SECONDS) -> str:
    expires_at = int(time.time()) + ttl_seconds
    signature = _sign_auth_session(username, expires_at)
    raw = f"{username}|{expires_at}|{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_auth_session(token: str) -> dict[str, object] | None:
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8")
        username, expires_text, signature = raw.split("|", 2)
        expires_at = int(expires_text)
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        return None

    if expires_at < int(time.time()):
        return None
    expected = _sign_auth_session(username, expires_at)
    if not hmac.compare_digest(signature, expected):
        return None
    if not hmac.compare_digest(username, AUTH_USERNAME):
        return None
    return {"username": username, "expires_at": expires_at}


def _cookie_value(cookie_header: str, name: str) -> str:
    for chunk in cookie_header.split(";"):
        key, _, value = chunk.strip().partition("=")
        if key == name:
            return value
    return ""


def _as_int(value: object, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_openclaw_settings() -> dict[str, object]:
    try:
        payload = json.loads(OPENCLAW_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "line_auto_enabled": bool(payload.get("line_auto_enabled", True)),
    }


def _write_openclaw_settings(settings: dict[str, object]) -> dict[str, object]:
    current = _read_openclaw_settings()
    current.update(settings)
    OPENCLAW_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OPENCLAW_SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OPENCLAW_SETTINGS_PATH)
    return current


def _is_recent_run_lock(max_age_hours: float = 6) -> bool:
    try:
        return RUN_LOCK_PATH.is_file() and (time.time() - RUN_LOCK_PATH.stat().st_mtime) < max_age_hours * 3600
    except OSError:
        return False


def _read_latest_job() -> dict[str, object] | None:
    try:
        raw = LATEST_JOB_PATH.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _job_compat_from_latest(latest: dict[str, object] | None) -> dict[str, object] | None:
    if not latest:
        return None
    status = str(latest.get("status") or "")
    return {
        "running": status == "running",
        "pid": latest.get("pid"),
        "last_started_at": latest.get("started_at"),
        "last_finished_at": latest.get("finished_at"),
        "last_success": True if status == "success" else False if status in {"failed", "stale"} else None,
        "last_error": latest.get("last_error"),
        "returncode": latest.get("returncode"),
        "job_id": latest.get("job_id"),
        "trigger_source": latest.get("trigger_source"),
        "status": latest.get("status"),
        "steps": latest.get("steps"),
        "log_path": latest.get("log_path"),
    }


def _latest_matches_manual_snapshot(latest: dict[str, object] | None, snapshot: dict[str, object]) -> bool:
    if not latest or latest.get("trigger_source") != "manual":
        return False
    if not snapshot.get("running"):
        return True

    latest_pid = latest.get("pid")
    snapshot_pid = snapshot.get("pid")
    if latest_pid and snapshot_pid and latest_pid == snapshot_pid:
        return True

    latest_started = str(latest.get("started_at") or "")
    snapshot_started = str(snapshot.get("last_started_at") or "")
    return bool(latest_started and snapshot_started and latest_started >= snapshot_started)


def _latest_job_snapshot() -> dict[str, object] | None:
    latest = _read_latest_job()
    if latest and latest.get("status") == "running" and not _is_recent_run_lock():
        latest = dict(latest)
        latest["status"] = "stale"
        latest["running"] = False
        latest["last_error"] = latest.get("last_error") or "job status is running but lock file is not active"
    return latest


def _upload_pipeline_is_busy() -> bool:
    latest = _latest_job_snapshot()
    current = _manual_job_snapshot()
    return bool(current.get("running") or _is_recent_run_lock() or (latest and latest.get("status") == "running"))


def _read_pending_upload_jobs() -> list[dict[str, object]]:
    try:
        payload = json.loads(PENDING_UPLOAD_JOBS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _write_pending_upload_jobs(jobs: list[dict[str, object]]) -> None:
    PENDING_UPLOAD_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PENDING_UPLOAD_JOBS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PENDING_UPLOAD_JOBS_PATH)


def _queue_pending_upload_job(folder: dict[str, object], *, trigger_source: str = "upload") -> None:
    folder_id = int(folder["id"])
    with PENDING_UPLOAD_LOCK:
        jobs = [job for job in _read_pending_upload_jobs() if int(job.get("folder_id") or 0) != folder_id]
        jobs.append({
            "folder_id": folder_id,
            "folder_slug": folder.get("folder_slug"),
            "trigger_source": trigger_source,
            "queued_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        })
        _write_pending_upload_jobs(jobs)


def _manual_job_snapshot() -> dict[str, object]:
    with JOB_LOCK:
        snapshot = dict(MANUAL_JOB)
    latest = _latest_job_snapshot()
    if _latest_matches_manual_snapshot(latest, snapshot):
        compat = _job_compat_from_latest(latest)
        if compat:
            snapshot.update(compat)
    return snapshot


def _set_manual_job(**updates: object) -> dict[str, object]:
    with JOB_LOCK:
        MANUAL_JOB.update(updates)
        return dict(MANUAL_JOB)


def _try_claim_manual_run() -> tuple[bool, dict[str, object]]:
    """Atomic check-and-reserve. On claimed=True, caller MUST either fill pid
    via _set_manual_job or call _abandon_manual_run on failure."""
    latest = _latest_job_snapshot()
    with JOB_LOCK:
        if (
            MANUAL_JOB.get("running")
            or _is_recent_run_lock()
            or (latest and latest.get("status") == "running")
        ):
            busy = dict(MANUAL_JOB)
            if latest and latest.get("trigger_source") == "manual":
                compat = _job_compat_from_latest(latest)
                if compat:
                    busy.update(compat)
            return False, busy
        MANUAL_JOB.update({
            "running": True,
            "pid": None,
            "status": "running",
            "job_id": None,
            "trigger_source": "manual",
            "last_started_at": _utc_now_iso(),
            "last_finished_at": None,
            "last_success": None,
            "last_error": None,
            "returncode": None,
            "steps": {},
            "log_path": None,
        })
        return True, dict(MANUAL_JOB)


def _abandon_manual_run(error: str) -> None:
    _set_manual_job(
        running=False,
        last_finished_at=_utc_now_iso(),
        last_success=False,
        last_error=error,
        returncode=None,
    )


def _status_with_manual_job(*, target_id: str | None = None) -> dict:
    payload = processing_status(target_id=target_id)
    payload["latest_job"] = _latest_job_snapshot()
    payload["manual_job"] = _manual_job_snapshot()
    return payload


def _watch_manual_process(process: subprocess.Popen) -> None:
    try:
        returncode = process.wait()
        time.sleep(0.2)
        latest = _latest_job_snapshot()
        compat = _job_compat_from_latest(latest) if latest and latest.get("trigger_source") == "manual" else None
        if compat:
            _set_manual_job(**compat)
        else:
            _set_manual_job(
                running=False,
                last_finished_at=_utc_now_iso(),
                last_success=returncode == 0,
                last_error=None if returncode == 0 else f"process exited with code {returncode}",
                returncode=returncode,
            )
        if returncode == 0:
            _prewarm_latest_thumbnails()
    except Exception as exc:
        _set_manual_job(
            running=False,
            last_finished_at=_utc_now_iso(),
            last_success=False,
            last_error=str(exc),
            returncode=None,
        )


def _parse_search(text: str) -> dict[str, object]:
    price_min, price_max = parse_price_bounds(text)
    return {
        "countries": extract_country(text),
        "regions": extract_region(text),
        "months": extract_months(text),
        "features": extract_features(text),
        "price_min": price_min,
        "price_max": price_max,
        "duration_days": extract_duration(text),
    }


def _has_meaningful_search_filters(filters: dict[str, object]) -> bool:
    return any(filters.get(key) for key in ("countries", "regions", "features", "price_min", "price_max", "duration_days"))


def _has_real_price(item: dict) -> bool:
    try:
        return int(item.get("price_from") or 0) >= 5000
    except (TypeError, ValueError):
        return False


def _prioritize_priced_items(payload: dict, limit: int) -> dict:
    copy = dict(payload)
    items = list(copy.get("items") or [])
    items.sort(key=lambda item: (str(item.get("indexed_at") or ""), str(item.get("source_time") or "")), reverse=True)
    items.sort(key=lambda item: 0 if _has_real_price(item) else 1)
    copy["items"] = items[:limit]
    copy["count"] = len(copy["items"])
    return copy


def _media_id(value: object) -> str:
    raw = str(value or "")
    token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    return token.rstrip("=")


def _decode_media_id(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")


def _resolve_project_file(raw: str) -> Path | None:
    if not raw:
        return None
    candidate = (PROJECT_ROOT / unquote(raw)).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _db_image_path(media_id: str, *, branded: bool = True) -> str | None:
    try:
        key = _decode_media_id(media_id)
    except Exception:
        return None

    with open_db(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # sidecar_path is unique, but image_path / branded_path are not — a
        # re-branded source can leave older rows behind. Pick the newest one
        # so /media?id=... always resolves to the current branded result.
        row = conn.execute(
            "SELECT sidecar_path, image_path, branded_path FROM itineraries "
            "WHERE sidecar_path = ? OR image_path = ? OR branded_path = ? "
            "ORDER BY indexed_at DESC LIMIT 1",
            (key, key, key),
        ).fetchone()
    if row is None:
        return None
    if branded:
        return row["branded_path"] or row["image_path"]
    return row["image_path"] or row["branded_path"]


def _thumbnail_path(source: Path, width: int) -> Path:
    stat = source.stat()
    digest = hashlib.sha1(
        f"{source.relative_to(PROJECT_ROOT).as_posix()}:{stat.st_mtime_ns}:{stat.st_size}:{width}".encode("utf-8")
    ).hexdigest()
    return THUMBNAIL_DIR / f"{digest}.jpg"


def _ensure_thumbnail(source: Path, width: int) -> Path:
    width = max(80, min(int(width or 360), 1200))
    target = _thumbnail_path(source, width)
    if target.is_file():
        return target

    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((width, width * 2))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(target, "JPEG", quality=78, optimize=True)
    return target


def _media_ids_to_files(media_ids: list[object]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for value in media_ids:
        media_id = str(value or "")
        raw = _db_image_path(media_id)
        if not raw:
            try:
                raw = _decode_media_id(media_id)
            except Exception:
                raw = ""
        candidate = _resolve_project_file(raw or "")
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        files.append(candidate)
    return files


def _copy_files_to_windows_clipboard(files: list[Path]) -> dict:
    if not files:
        return {"ok": False, "copied": 0, "error": "no files"}
    if not CLIPBOARD_SCRIPT.is_file():
        return {"ok": False, "copied": 0, "error": "clipboard bridge script missing"}

    command = [
        "powershell.exe",
        "-NoProfile",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(CLIPBOARD_SCRIPT),
        *[str(path) for path in files],
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if completed.returncode != 0:
        return {
            "ok": False,
            "copied": 0,
            "error": (completed.stderr or completed.stdout or "clipboard bridge failed").strip(),
        }
    return {
        "ok": True,
        "copied": len(files),
        "files": [str(path.relative_to(PROJECT_ROOT)) for path in files],
        "message": (completed.stdout or "").strip(),
    }


def _zip_bytes_for_files(files: list[Path]) -> bytes:
    buffer = io.BytesIO()
    seen: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, path in enumerate(files, start=1):
            suffix = path.suffix.lower() or ".jpg"
            base_name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or "travel_dm"
            name = f"{index:02d}_{base_name}{suffix}"
            while name in seen:
                name = f"{index:02d}_{base_name}_{len(seen) + 1}{suffix}"
            seen.add(name)
            archive.write(path, arcname=name)
    return buffer.getvalue()


_LINE_FILENAME_RE = re.compile(r"^(.+?)_\d{4}_line_\d+(?:_\d+)+\.[A-Za-z]+$")
_UPLOAD_DISPLAY_NAME_CACHE: dict[str, str] = {}


def _lookup_upload_folder_display_name(folder_slug: str) -> str | None:
    """Look up upload_catalog for display_name by folder_slug. Cache hits
    only; None values re-query so a missing catalog DB recovers as soon as
    one appears."""
    cached = _UPLOAD_DISPLAY_NAME_CACHE.get(folder_slug)
    if cached:
        return cached
    try:
        with open_db(CATALOG_DB_PATH) as conn:
            row = conn.execute(
                "SELECT display_name FROM upload_folders WHERE folder_slug = ? LIMIT 1",
                (folder_slug,),
            ).fetchone()
    except sqlite3.Error:
        return None
    display = (row[0] if row else "") or ""
    if display:
        _UPLOAD_DISPLAY_NAME_CACHE[folder_slug] = display
        return display
    return None


def _humanize_source(item: dict) -> tuple[str, str]:
    """Return (label, kind) describing the human-readable source. kind is
    'line' (auto-crawled LINE) or 'upload' (manual upload) or 'unknown'.
    The label is what we want on screen — never the raw batch slug."""
    target_id = str(item.get("target_id") or "")
    group_name = str(item.get("group_name") or "")
    image_path = str(item.get("image_path") or item.get("branded_path") or "")

    # LINE auto-fetch batch slug — derive real group from filename prefix,
    # because RPA didn't write source.groupName into the sidecar and reindex
    # falls back to the run folder name, mashing all groups together.
    if target_id.startswith("line_auto_") or group_name.startswith("line_auto_"):
        leaf = image_path.replace("\\", "/").rsplit("/", 1)[-1]
        match = _LINE_FILENAME_RE.match(leaf)
        if match:
            return (match.group(1), "line")
        # Fallback: skip 'line_auto_YYYYMMDD_HHMMSS_' (4 tokens) to find groups
        rest = target_id.split("_", 4)
        if len(rest) >= 5:
            return (rest[4], "line")
        return (target_id or group_name, "line")

    # Manual upload folder — look up display_name from upload_catalog
    if target_id.startswith("upload_") or group_name.startswith("upload_"):
        slug = target_id or group_name
        display = _lookup_upload_folder_display_name(slug)
        if display:
            return (display, "upload")
        # Fallback: strip prefix + timestamp tokens (upload_YYYYMMDD_HHMMSS_)
        rest = slug.split("_", 3)
        if len(rest) >= 4:
            return (rest[3], "upload")
        return (slug, "upload")

    # Pre-batch LINE records: target_id IS the group name
    if group_name:
        return (group_name, "line")
    if target_id:
        return (target_id, "line")
    return ("Agent", "unknown")


def _with_media_urls(payload: dict) -> dict:
    def convert_item(item: dict) -> dict:
        copy = dict(item)
        image_key = copy.get("sidecar_path") or copy.get("branded_path") or copy.get("image_path")
        if image_key:
            media_id = _media_id(image_key)
            copy["media_id"] = media_id
            copy["image_url"] = f"/media?id={media_id}"
            copy["thumbnail_url"] = f"/media/thumbnail?id={media_id}&w=360"
            # preview_url serves the full branded file (brand_stitcher's JPEG q92,
            # already capped at outputMaxWidth=1200). Going through
            # /media/thumbnail at w=1200 re-encoded it at q78 with PIL.thumbnail,
            # producing a visibly softer modal preview than the same file shown
            # in the upload workspace via /media?path=... (branded_url).
            copy["preview_url"] = f"/media?id={media_id}"
        source_label, source_kind = _humanize_source(item)
        copy["source_label"] = source_label
        copy["source_kind"] = source_kind
        return copy

    copy = dict(payload)
    if isinstance(copy.get("items"), list):
        copy["items"] = [convert_item(item) for item in copy["items"]]
    if isinstance(copy.get("groups"), list):
        groups = []
        for group in copy["groups"]:
            group_copy = dict(group)
            if isinstance(group_copy.get("items"), list):
                group_copy["items"] = [convert_item(item) for item in group_copy["items"]]
            groups.append(group_copy)
        copy["groups"] = groups
    return copy


def _annotation_key(source_kind: str, source_key: object) -> str:
    return f"{source_kind}:{str(source_key or '').strip()}"


def _read_item_annotations() -> dict[str, dict[str, object]]:
    try:
        data = json.loads(ITEM_ANNOTATIONS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def _write_item_annotations(data: dict[str, dict[str, object]]) -> None:
    ITEM_ANNOTATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ITEM_ANNOTATIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ITEM_ANNOTATIONS_PATH)


def _item_annotation(source_kind: str, source_key: object) -> dict[str, object]:
    with ITEM_ANNOTATIONS_LOCK:
        return dict(_read_item_annotations().get(_annotation_key(source_kind, source_key)) or {})


def _save_item_annotation(source_kind: str, source_key: object, patch: dict[str, object]) -> dict[str, object]:
    key = _annotation_key(source_kind, source_key)
    with ITEM_ANNOTATIONS_LOCK:
        data = _read_item_annotations()
        current = dict(data.get(key) or {})
        current.update(patch)
        current["updated_at"] = _utc_now_iso()
        data[key] = current
        _write_item_annotations(data)
        return dict(current)


def _tag_text_values(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_ocr_tag_text(value.get("tag") if isinstance(value, dict) else value)
        if text and text != SYSTEM_TAGS_CLEARED_SENTINEL and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _manual_tag_values(tags: object) -> list[str]:
    if not isinstance(tags, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        text = _normalize_ocr_tag_text(tag.get("tag") if isinstance(tag, dict) else tag)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _source_system_tag_values(system_tags: list[dict[str, object]]) -> list[str]:
    return _tag_text_values(system_tags)


def _effective_system_tag_values(source_tags: list[str], override_values: list[str]) -> list[str]:
    if SYSTEM_TAGS_CLEARED_SENTINEL in override_values:
        return [tag for tag in override_values if tag != SYSTEM_TAGS_CLEARED_SENTINEL]
    return override_values if override_values else source_tags


def _replace_upload_manual_tags(image_id: int, desired_values: list[str]) -> None:
    current = list_manual_tags(image_id)
    current_by_value = {
        str(tag.get("tag") or "").strip(): tag
        for tag in current
        if str(tag.get("tag") or "").strip()
    }
    desired = [value for value in desired_values if value]
    desired_set = set(desired)
    for value, tag in current_by_value.items():
        if value not in desired_set:
            delete_manual_tag(int(tag["id"]))
    for value in desired:
        if value not in current_by_value:
            add_manual_tag(image_id, value)


def _upload_detail_source(folder: dict[str, object], image_path: str = "") -> tuple[str, str]:
    source = str(folder.get("source") or "").strip()
    if source == "line-auto":
        leaf = str(image_path or "").replace("\\", "/").rsplit("/", 1)[-1]
        match = _LINE_FILENAME_RE.match(leaf)
        if match:
            return "line-auto", match.group(1)
        groups = [
            str(group).strip()
            for group in folder.get("line_groups") or []
            if str(group).strip()
        ]
        label = " / ".join(groups) or str(
            folder.get("display_name") or folder.get("folder_slug") or "LINE 自動爬取"
        )
        return "line-auto", label
    label = str(folder.get("display_name") or folder.get("folder_slug") or "手動上傳")
    return "upload", label


def _upload_item_detail(image_id: int) -> dict[str, object] | None:
    record = _upload_image_record(image_id)
    if record is None:
        return None
    image, folder = record
    current_path = _find_current_image_path(image, folder)
    current_rel = current_path.relative_to(PROJECT_ROOT).as_posix() if current_path else str(image.get("stored_path") or "")
    media_id = _media_id(current_rel) if current_rel else ""
    source_tags = _source_system_tag_values(_system_tags_for_same_sha_image(image_id, current_path))
    override_values = _normalize_ocr_tag_values(image.get("ocr_tags_override"))
    manual_tags = list_manual_tags(image_id)
    source_kind, source_label = _upload_detail_source(folder, current_rel)
    return {
        "source_kind": source_kind,
        "source_key": str(image_id),
        "image_id": image_id,
        "folder_id": folder.get("id"),
        "image_path": current_rel,
        "media_id": media_id,
        "image_url": f"/media?id={media_id}" if media_id else "",
        "thumbnail_url": f"/media/thumbnail?id={media_id}&w=360" if media_id else "",
        "source_label": source_label,
        "source_time": image.get("uploaded_at") or "",
        "uploaded_at": image.get("uploaded_at") or "",
        "indexed_at": image.get("updated_at") or image.get("uploaded_at") or "",
        "original_filename": image.get("original_filename") or "",
        "folder_note": folder.get("note") or "",
        "system_tags": _effective_system_tag_values(source_tags, override_values),
        "source_system_tags": source_tags,
        "ocr_tags_override": override_values,
        "manual_tags": manual_tags,
        "reference_text": image.get("reference_text") or "",
        "manual_note": image.get("manual_note") or "",
        "raw_text": " ".join(_sidecar_text_values(_sidecar_payload_for_image(current_path))),
        "editable": True,
    }


def _line_item_detail(sidecar_path: str, params: dict[str, list[str]] | None = None) -> dict[str, object] | None:
    sidecar = _resolve_project_file(sidecar_path)
    if sidecar is None:
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    item = {
        "sidecar_path": sidecar.relative_to(PROJECT_ROOT).as_posix(),
        "image_path": _first(params or {}, "image_path"),
        "target_id": _first(params or {}, "target_id") or str(source.get("targetId") or source.get("target_id") or ""),
        "group_name": _first(params or {}, "group_name") or str(source.get("groupName") or source.get("group_name") or ""),
    }
    source_label, _ = _humanize_source(item)
    annotation = _item_annotation("line", item["sidecar_path"])
    source_tags = _source_system_tag_values(_sidecar_system_tags(payload))
    override_values = _normalize_ocr_tag_values(annotation.get("ocr_tags_override"))
    raw_text = "\n".join(_sidecar_text_values(payload))
    image_path = _resolve_project_file(str(item.get("image_path") or "")) or sidecar.with_suffix("")
    return {
        "source_kind": "line",
        "source_key": item["sidecar_path"],
        "sidecar_path": item["sidecar_path"],
        "source_label": source_label,
        "source_time": source.get("savedAt") or payload.get("savedAt") or _first(params or {}, "source_time"),
        "original_filename": image_path.name,
        "folder_note": "",
        "system_tags": _effective_system_tag_values(source_tags, override_values),
        "source_system_tags": source_tags,
        "ocr_tags_override": override_values,
        "manual_tags": [
            {"id": f"line-{index}", "tag": value}
            for index, value in enumerate(_manual_tag_values(annotation.get("manual_tags")), 1)
        ],
        "reference_text": str(annotation.get("reference_text")) if "reference_text" in annotation else raw_text,
        "manual_note": str(annotation.get("manual_note") or ""),
        "raw_text": raw_text,
        "editable": True,
    }


def _query_item_detail(params: dict[str, list[str]]) -> dict[str, object] | None:
    source = _first(params, "source")
    image_id = _as_int(_first(params, "image_id"), None)
    if image_id is None:
        for value in (
            _first(params, "sidecar_path"),
            _first(params, "image_path"),
            _first(params, "branded_path"),
        ):
            if not value:
                continue
            with open_db(CATALOG_DB_PATH) as conn:
                row = conn.execute(
                    """
                    SELECT image_id
                    FROM uploaded_image_search_index
                    WHERE sidecar_path = ? OR image_path = ? OR branded_path = ?
                    LIMIT 1
                    """,
                    (value, value, value),
                ).fetchone()
            if row:
                image_id = int(row[0])
                break
    if source == "upload" or image_id is not None:
        if image_id is not None:
            return _upload_item_detail(int(image_id))
        sidecar_path = _detail_sidecar_path(params)
        return _line_item_detail(sidecar_path, params) if sidecar_path else None
    return _line_item_detail(_detail_sidecar_path(params), params)


def _detail_sidecar_path(params: dict[str, list[str]]) -> str:
    for key in ("sidecar_path", "image_path", "branded_path"):
        value = _first(params, key)
        if not value:
            continue
        resolved = _resolve_project_file(value)
        if resolved and resolved.suffix.lower() == ".json":
            return value
        json_value = f"{value}.json"
        if _resolve_project_file(json_value):
            return json_value
    return _first(params, "sidecar_path")


def _system_tag_override_for_update(source_tags: list[str], requested_tags: object) -> list[str] | None:
    if not isinstance(requested_tags, list):
        return None
    source_set = set(source_tags)
    desired = [tag for tag in _tag_text_values(requested_tags) if tag in source_set]
    if desired == source_tags:
        return []
    if not desired and source_tags:
        return [SYSTEM_TAGS_CLEARED_SENTINEL]
    return desired


def _prewarm_payload_thumbnails(payload: dict, *, limit: int = 80, width: int = 360) -> None:
    items = list(payload.get("items") or [])
    if isinstance(payload.get("groups"), list):
        for group in payload["groups"]:
            items.extend(group.get("items") or [])

    warmed = 0
    for item in items:
        if warmed >= limit:
            return
        raw = item.get("branded_path") or item.get("image_path") or item.get("sidecar_path")
        candidate = _resolve_project_file(str(raw or ""))
        if candidate is None:
            continue
        try:
            _ensure_thumbnail(candidate, width)
            warmed += 1
        except Exception:
            continue


def _prewarm_latest_thumbnails(*, limit: int = 80) -> None:
    try:
        payload = query_latest_results(today=True, composed_only=True, limit=limit)
        _prewarm_payload_thumbnails(payload, limit=limit)
    except Exception:
        pass


SUPPORTED_UPLOAD_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_FILE_BYTES = 15 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 200 * 1024 * 1024
MAX_UPLOAD_FILE_COUNT = 50
MIN_UPLOAD_IMAGE_EDGE_PX = 50
FALLBACK_MIN_UPLOAD_IMAGE_WIDTH_PX = 620
UPLOAD_FOLDER_STALE_AFTER_SECONDS = 60 * 60
UPLOAD_FOLDER_LOCK_GRACE_SECONDS = 5 * 60
BRANDING_CONFIG_PATH = PROJECT_ROOT / "config" / "branding.json"


def _minimum_brandable_width(
    logo_width: int,
    logo_width_ratio: float,
    logo_scale_min: float,
    logo_padding_ratio: float,
) -> int:
    if logo_width <= 0 or logo_width_ratio <= 0 or logo_scale_min <= 0:
        return FALLBACK_MIN_UPLOAD_IMAGE_WIDTH_PX
    padding_ratio = max(0.0, min(float(logo_padding_ratio or 0.0), 0.49))
    approximate = max(
        MIN_UPLOAD_IMAGE_EDGE_PX,
        int(math.ceil((logo_width * logo_scale_min) / logo_width_ratio)),
    )
    if padding_ratio:
        approximate = int(math.ceil(approximate / (1.0 - (2.0 * padding_ratio))))

    width = max(MIN_UPLOAD_IMAGE_EDGE_PX, approximate)
    while True:
        pad = int(width * padding_ratio)
        available_w = max(1, width - (pad * 2))
        scale = (available_w * logo_width_ratio) / logo_width
        if scale >= logo_scale_min:
            return width
        width += 1


def _upload_image_size_requirement() -> tuple[int, int]:
    try:
        cfg = json.loads(BRANDING_CONFIG_PATH.read_text(encoding="utf-8"))
        logo_path = (PROJECT_ROOT / str(cfg["logoPath"])).resolve()
        with Image.open(logo_path) as logo:
            logo_width = int(logo.size[0])
        min_width = _minimum_brandable_width(
            logo_width,
            float(cfg.get("logoWidthRatio") or 0),
            float(cfg.get("logoScaleMin") or 0),
            float(cfg.get("logoPaddingRatio") or 0),
        )
    except Exception:
        min_width = FALLBACK_MIN_UPLOAD_IMAGE_WIDTH_PX
    return max(MIN_UPLOAD_IMAGE_EDGE_PX, min_width), MIN_UPLOAD_IMAGE_EDGE_PX


def _validate_upload_image_dimensions(content: bytes) -> str | None:
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            image.verify()
    except Exception:
        return "圖片無法讀取或格式損壞"

    min_width, min_edge = _upload_image_size_requirement()
    if width < min_edge or height < min_edge or width < min_width:
        return (
            f"圖片太小：{width}x{height}px。品牌組圖需要寬度至少 {min_width}px，"
            f"且寬、高都必須至少 {min_edge}px。請上傳 LINE 原圖或較高解析度圖片。"
        )
    return None


def _extract_multipart_boundary(content_type: str) -> bytes:
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not match:
        raise ValueError("multipart boundary missing")
    return match.group(1).encode("utf-8")


def _parse_multipart_form(content_type: str, body: bytes) -> tuple[dict[str, str], list[dict[str, object]]]:
    boundary = _extract_multipart_boundary(content_type)
    delimiter = b"--" + boundary
    fields: dict[str, str] = {}
    files: list[dict[str, object]] = []
    for part in body.split(delimiter):
        if not part:
            continue
        # The closing "--boundary--" piece starts with "--" (possibly followed
        # by "\r\n<epilogue>"). Preamble pieces are handled by the not-part check
        # above (they may be empty) or are skipped at the partition-not-found
        # check below.
        if part.startswith(b"--"):
            continue
        # Each real part is "\r\n<headers>\r\n\r\n<body>\r\n" — strip exactly
        # the structural CRLFs. Previously this used part.strip() + rstrip,
        # which are character-greedy and silently chewed off whitespace bytes
        # at the end of binary file payloads.
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        header_blob, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = header_blob.decode("utf-8", errors="replace").split("\r\n")
        disposition = ""
        for header in headers:
            name, _, value = header.partition(":")
            if name.lower() == "content-disposition":
                disposition = value.strip()
                break
        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue
        field_name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if filename_match:
            filename = Path(filename_match.group(1)).name
            if filename:
                files.append({"field": field_name, "filename": filename, "content": content})
        else:
            fields[field_name] = content.decode("utf-8", errors="replace")
    return fields, files


def _find_current_image_path(image: dict[str, object], folder: dict[str, object]) -> Path | None:
    stored = _resolve_project_file(str(image.get("stored_path") or ""))
    if stored is not None:
        return stored
    digest = str(image.get("sha256") or "")
    if not digest:
        return None
    base = folder_target_path(folder)
    for subdir in ("inbox", "travel", "other", "review", "error", "branded"):
        folder_path = base / subdir
        if not folder_path.exists():
            continue
        for candidate in folder_path.iterdir():
            if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_UPLOAD_EXT:
                continue
            try:
                if file_sha256(candidate) == digest:
                    return candidate
            except OSError:
                continue
    return None


def _normalize_ocr_tag_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or _PUNCTUATION_ONLY_TAG.fullmatch(text):
        return ""
    if _OPENCC_T2TW is not None:
        text = _OPENCC_T2TW.convert(text)
    else:
        text = text.translate(_OCR_TAG_FALLBACK_TRANSLATION)
    return text.strip()


def _normalize_ocr_tag_values(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value == SYSTEM_TAGS_CLEARED_SENTINEL:
            normalized.append(value)
            continue
        text = _normalize_ocr_tag_text(value)
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


def _add_system_tag(tags: list[dict[str, object]], seen: set[str], value: object, field: str) -> None:
    text = _normalize_ocr_tag_text(value)
    if not text or text in seen:
        return
    seen.add(text)
    tags.append({"tag": text, "source": "ocr", "field": field})


def _format_month_tag(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.fullmatch(r"0?([1-9]|1[0-2])", text)
    if match:
        return f"{int(match.group(1))}月"
    return text if text.endswith("月") else text


def _sidecar_system_tags(payload: dict[str, object]) -> list[dict[str, object]]:
    tags: list[dict[str, object]] = []
    seen: set[str] = set()

    sources = [payload]
    first_pass = payload.get("firstPassSummary")
    if isinstance(first_pass, dict):
        sources.append(first_pass)

    for source in sources:
        for key in ("countries", "regions", "features"):
            values = source.get(key)
            if isinstance(values, list):
                for value in values:
                    _add_system_tag(tags, seen, value, key)
        months = source.get("months")
        if isinstance(months, list):
            for value in months:
                _add_system_tag(tags, seen, _format_month_tag(value), "months")
        duration = source.get("duration_days")
        if duration:
            _add_system_tag(tags, seen, f"{duration}\u5929", "duration_days")
        price = source.get("price_from")
        if price:
            _add_system_tag(tags, seen, f"{price}\u5143\u8d77", "price_from")

    ocr = payload.get("ocr")
    if isinstance(ocr, dict):
        hits = ocr.get("hits")
        if isinstance(hits, str):
            for value in re.split(r"[,，、\s]+", hits):
                clean = value.strip()
                if clean and not (clean.startswith("<") and clean.endswith(">")):
                    _add_system_tag(tags, seen, clean, "ocr_hits")

    classification = payload.get("domain") or (ocr.get("classification") if isinstance(ocr, dict) else None)
    if classification and classification != "travel":
        _add_system_tag(tags, seen, classification, "classification")
    return tags


def _sidecar_payload_for_image(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    sidecar = path.with_suffix(path.suffix + ".json")
    if not sidecar.is_file():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _sidecar_text_values(payload: dict[str, object]) -> list[str]:
    values: list[str] = []
    ocr = payload.get("ocr")
    if isinstance(ocr, dict):
        for key in ("text", "hits"):
            value = _normalize_ocr_tag_text(ocr.get(key))
            if value:
                values.append(value)
    return values


def _sidecar_query_fields(payload: dict[str, object]) -> dict[str, object]:
    sources = [payload]
    first_pass = payload.get("firstPassSummary")
    if isinstance(first_pass, dict):
        sources.append(first_pass)

    result: dict[str, object] = {
        "countries": [],
        "regions": [],
        "months": [],
        "duration_days": None,
        "price_from": None,
    }
    for source in sources:
        for key in ("countries", "regions"):
            values = source.get(key)
            if isinstance(values, list):
                merged = list(result[key])
                for value in values:
                    text = _normalize_ocr_tag_text(value)
                    if text and text not in merged:
                        merged.append(text)
                result[key] = merged
        months = source.get("months")
        if isinstance(months, list):
            merged_months = list(result["months"])
            for value in months:
                try:
                    month = int(str(value).strip())
                except ValueError:
                    continue
                if 1 <= month <= 12 and month not in merged_months:
                    merged_months.append(month)
            result["months"] = merged_months
        if result["duration_days"] is None and source.get("duration_days"):
            try:
                result["duration_days"] = int(source["duration_days"])
            except (TypeError, ValueError):
                pass
        if result["price_from"] is None and source.get("price_from"):
            try:
                result["price_from"] = int(source["price_from"])
            except (TypeError, ValueError):
                pass
    return result


def _system_tags_for_image(path: Path | None) -> list[dict[str, object]]:
    payload = _sidecar_payload_for_image(path)
    if not payload:
        return []
    return _sidecar_system_tags(payload)


def _merge_system_tags(tag_groups: list[list[dict[str, object]]]) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[str] = set()
    for tags in tag_groups:
        for tag in tags:
            value = _normalize_ocr_tag_text(tag.get("tag") if isinstance(tag, dict) else tag)
            if not value or value in seen:
                continue
            seen.add(value)
            item = dict(tag) if isinstance(tag, dict) else {"tag": value, "source": "ocr"}
            item["tag"] = value
            merged.append(item)
    return merged


def _merge_sidecar_query_fields(payloads: list[dict[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {
        "countries": [],
        "regions": [],
        "months": [],
        "duration_days": None,
        "price_from": None,
    }
    for payload in payloads:
        fields = _sidecar_query_fields(payload)
        for key in ("countries", "regions", "months"):
            merged = list(result[key])
            for value in fields.get(key) or []:
                if value not in merged:
                    merged.append(value)
            result[key] = merged
        if result["duration_days"] is None and fields.get("duration_days") is not None:
            result["duration_days"] = fields["duration_days"]
        if result["price_from"] is None and fields.get("price_from") is not None:
            result["price_from"] = fields["price_from"]
    return result


def _same_sha_sidecar_payloads(image_id: int, current_path: Path | None = None) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for related_image_id in same_sha_image_ids(image_id) or [image_id]:
        path = current_path if related_image_id == image_id else None
        record = _upload_image_record(related_image_id)
        if record is not None:
            image, folder = record
            path = _find_current_image_path(image, folder)
        if path is None:
            continue
        path_key = str(path.resolve())
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        payload = _sidecar_payload_for_image(path)
        if payload:
            payloads.append(payload)
    return payloads


def _system_tags_for_same_sha_image(image_id: int, current_path: Path | None = None) -> list[dict[str, object]]:
    path = current_path
    if path is None:
        record = _upload_image_record(image_id)
        if record is not None:
            image, folder = record
            path = _find_current_image_path(image, folder)
    return _system_tags_for_image(path)


def _folder_pipeline_counts(folder: dict[str, object]) -> dict[str, int]:
    base = folder_target_path(folder)
    ocr_count = 0
    for subdir in ("travel", "review", "other", "error"):
        folder_path = base / subdir
        if folder_path.is_dir():
            ocr_count += sum(1 for item in folder_path.glob("*.json") if item.is_file())

    branded_dir = base / "branded"
    composed_count = 0
    if branded_dir.is_dir():
        composed_count = sum(
            1
            for item in branded_dir.iterdir()
            if item.is_file() and item.suffix.lower() in SUPPORTED_UPLOAD_EXT
        )
    return {"ocr_count": ocr_count, "composed_count": composed_count}


def _branded_image_lookup(folder: dict[str, object]) -> tuple[dict[str, Path], dict[str, Path]]:
    branded_dir = folder_target_path(folder) / "branded"
    if not branded_dir.is_dir():
        return {}, {}

    by_source: dict[str, Path] = {}
    by_hash: dict[str, Path] = {}
    for branded in branded_dir.iterdir():
        if not branded.is_file() or branded.suffix.lower() not in SUPPORTED_UPLOAD_EXT:
            continue
        sidecar = branded.with_suffix(branded.suffix + ".json")
        if not sidecar.is_file():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        source_path_value = (
            source.get("imagePath")
            or source.get("image_path")
            or payload.get("image_path")
            or payload.get("source_image_path")
        )
        source_path = _resolve_project_file(str(source_path_value or ""))
        if source_path is None:
            continue
        by_source[source_path.relative_to(PROJECT_ROOT).as_posix()] = branded
        try:
            by_hash.setdefault(file_sha256(source_path), branded)
        except OSError:
            pass
    return by_source, by_hash


def _folder_image_progress(folder: dict[str, object]) -> dict[str, int]:
    by_source, by_hash = _branded_image_lookup(folder)
    images = list_images(int(folder["id"]))
    ocr_count = 0
    composed_count = 0
    for image in images:
        current_path = _find_current_image_path(image, folder)
        current_rel = current_path.relative_to(PROJECT_ROOT).as_posix() if current_path is not None else ""
        has_ocr = (
            image.get("ocr_status") == "success"
            or (current_path is not None and current_path.with_suffix(current_path.suffix + ".json").is_file())
        )
        has_composed = bool(by_source.get(current_rel) or by_hash.get(str(image.get("sha256") or "")))
        if has_ocr:
            ocr_count += 1
        if has_composed:
            composed_count += 1
    return {"ocr_count": ocr_count, "composed_count": composed_count, "image_count": len(images)}


def _folder_with_file_progress(folder: dict[str, object]) -> dict[str, object]:
    counts = _folder_image_progress(folder)
    copy = {**folder, **counts}
    image_count = int(copy.get("image_count") or 0)
    composed_count = int(copy.get("composed_count") or 0)
    ocr_count = int(copy.get("ocr_count") or 0)
    step_statuses = dict(copy.get("step_statuses") or {})
    status = str(copy.get("status") or "")

    if image_count > 0 and composed_count >= image_count:
        copy["status"] = "success"
        copy["current_step"] = "done"
        copy["step_statuses"] = {
            **step_statuses,
            "upload": "success",
            "ocr": "success",
            "compose": "success",
            "index": "success",
        }
    elif image_count > 0 and ocr_count >= image_count and status not in {"failed", "stale"}:
        copy["status"] = "running"
        copy["current_step"] = "compose"
        copy["step_statuses"] = {
            **step_statuses,
            "upload": step_statuses.get("upload") or "success",
            "ocr": "success",
            "compose": step_statuses.get("compose") or "pending",
        }
    return copy


def _parse_utc_epoch(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def _folder_recovery_state(folder: dict[str, object]) -> dict[str, object]:
    status = str(folder.get("status") or "")
    current_step = str(folder.get("current_step") or "")
    step_statuses = dict(folder.get("step_statuses") or {})
    active_steps = {"ocr", "compose", "index"}
    failed_steps = [name for name in ("ocr", "compose", "index") if step_statuses.get(name) == "failed"]
    reasons: list[str] = []

    latest = folder.get("job") if isinstance(folder.get("job"), dict) else None
    if latest and latest.get("status") in {"stale", "failed"}:
        reasons.append(str(latest.get("last_error") or latest.get("status") or "latest job is not active"))

    if failed_steps:
        reasons.append(f"{failed_steps[0]} step failed")

    if status == "stale":
        reasons.append("job status is stale")
    updated_epoch = _parse_utc_epoch(folder.get("updated_at"))
    age_seconds = time.time() - updated_epoch if updated_epoch is not None else None
    if (
        status == "running"
        and current_step in active_steps
        and not _is_recent_run_lock()
        and (age_seconds is None or age_seconds >= UPLOAD_FOLDER_LOCK_GRACE_SECONDS)
    ):
        reasons.append("job lock is not active")

    if status == "running" and current_step in active_steps and updated_epoch is not None:
        if age_seconds is not None and age_seconds >= UPLOAD_FOLDER_STALE_AFTER_SECONDS:
            reasons.append("no folder progress for more than 60 minutes")

    stuck_step = failed_steps[0] if failed_steps else current_step if current_step in active_steps else ""
    if not stuck_step:
        for name in ("ocr", "compose", "index"):
            if step_statuses.get(name) == "running":
                stuck_step = name
                break

    stale = bool(reasons)
    return {
        "stale": stale,
        "reason": "; ".join(dict.fromkeys(reasons)),
        "stuck_step": stuck_step,
        "can_retry": stale,
        "can_archive": stale,
        "can_mark_failed": stale,
        "can_delete_images": stale or status in {"pending", "failed", "success", "stale"},
    }


def _branded_images_by_source(folder: dict[str, object]) -> dict[str, Path]:
    return _branded_image_lookup(folder)[0]


def _folder_with_runtime_status(folder: dict[str, object]) -> dict[str, object]:
    latest = _latest_job_snapshot()
    copy = dict(folder)
    if latest and latest.get("folder_id") == folder.get("id"):
        copy["status"] = latest.get("status") or copy.get("status")
        copy["current_step"] = "done" if latest.get("status") == "success" else copy.get("current_step")
        copy["step_statuses"] = {
            **(copy.get("step_statuses") or {}),
            **{
                name: step.get("status")
                for name, step in (latest.get("steps") or {}).items()
                if isinstance(step, dict)
            },
        }
        copy["job"] = latest
    copy = _folder_with_file_progress(copy)
    copy["recovery"] = _folder_recovery_state(copy)
    return copy


def _image_flow_label(image: dict[str, object], folder: dict[str, object]) -> str:
    current_step = str(folder.get("current_step") or "")
    folder_status = str(folder.get("status") or "")
    has_ocr = (
        image.get("ocr_status") == "success"
        or bool(image.get("system_tags"))
        or bool(image.get("ocr_tags_override"))
    )
    has_composed = (
        image.get("compose_status") == "success"
        or bool(image.get("branded_path"))
        or bool(image.get("branded_url"))
    )

    if has_composed or folder_status == "success" or current_step == "done":
        return "執行完成"
    if has_ocr or current_step == "compose" or image.get("compose_status") == "running":
        return "組合中"
    return "辨識中"


def _folder_detail(
    folder: dict[str, object],
    *,
    uploaded_from: str | None = None,
    uploaded_to: str | None = None,
) -> dict[str, object]:
    folder = _folder_with_runtime_status(folder)
    branded_by_source, branded_by_hash = _branded_image_lookup(folder)
    images = []
    for image in list_images(int(folder["id"]), uploaded_from=uploaded_from, uploaded_to=uploaded_to):
        current_path = _find_current_image_path(image, folder)
        image_copy = dict(image)
        image_copy["ocr_tags_override"] = _normalize_ocr_tag_values(image_copy.get("ocr_tags_override"))
        if current_path is not None:
            rel = current_path.relative_to(PROJECT_ROOT).as_posix()
            media_rel = quote(rel, safe="/")
            image_copy["current_path"] = rel
            image_copy["media_id"] = _media_id(rel)
            image_copy["image_url"] = f"/media?path={media_rel}"
            image_copy["thumbnail_url"] = f"/media/thumbnail?path={media_rel}&w=360"
            branded = branded_by_source.get(rel) or branded_by_hash.get(str(image.get("sha256") or ""))
            if branded is not None:
                branded_rel = branded.relative_to(PROJECT_ROOT).as_posix()
                branded_media_rel = quote(branded_rel, safe="/")
                image_copy["branded_path"] = branded_rel
                image_copy["branded_url"] = f"/media?path={branded_media_rel}"
                image_copy["branded_thumbnail_url"] = f"/media/thumbnail?path={branded_media_rel}&w=360"
        image_copy["manual_tags"] = list_manual_tags(int(image["id"]))
        image_copy["system_tags"] = _system_tags_for_same_sha_image(int(image["id"]), current_path)
        image_copy["flow_label"] = _image_flow_label(image_copy, folder)
        images.append(image_copy)
    folder["downloadable_count"] = sum(1 for image in images if image.get("flow_label") == "執行完成" and image.get("branded_path"))
    return {"folder": folder, "images": images}


def _folder_summary(folder: dict[str, object]) -> dict[str, object]:
    return _folder_with_runtime_status(folder)


def _folder_can_be_archived(folder: dict[str, object]) -> tuple[bool, str]:
    status = str(folder.get("status") or "")
    image_count = int(folder.get("image_count") or 0)
    recovery = folder.get("recovery") if isinstance(folder.get("recovery"), dict) else _folder_recovery_state(folder)
    if image_count == 0:
        return True, ""
    if status in {"success", "failed", "stale"} or recovery.get("can_archive"):
        return True, ""
    return False, "資料夾仍在 OCR / 組圖流程中，完成或失敗後才能刪除。"


def _image_can_be_archived(folder: dict[str, object], image: dict[str, object] | None = None) -> tuple[bool, str]:
    folder = _folder_with_runtime_status(folder)
    status = str(folder.get("status") or "")
    recovery = folder.get("recovery") if isinstance(folder.get("recovery"), dict) else {}
    image_failed = bool(image and (image.get("ocr_status") == "failed" or image.get("compose_status") == "failed"))
    if status == "running" and not recovery.get("stale") and not image_failed:
        return False, "資料夾仍在正常處理中，請等完成、失敗或中斷後再移除單張圖片。"
    return True, ""


def _folder_download_files(
    folder: dict[str, object],
    *,
    image_ids: list[object] | None = None,
    uploaded_from: str | None = None,
    uploaded_to: str | None = None,
) -> tuple[list[Path], list[dict[str, object]]]:
    selected_ids = {int(value) for value in image_ids or [] if _as_int(value) is not None}
    detail = _folder_detail(folder, uploaded_from=uploaded_from, uploaded_to=uploaded_to)
    files: list[Path] = []
    skipped: list[dict[str, object]] = []
    seen: set[Path] = set()
    for image in detail["images"]:
        image_id = int(image.get("id") or 0)
        if selected_ids and image_id not in selected_ids:
            continue
        label = str(image.get("flow_label") or "")
        if label != "執行完成":
            skipped.append({"id": image_id, "reason": "流程尚未完成"})
            continue
        candidate = _resolve_project_file(str(image.get("branded_path") or ""))
        if candidate is None:
            skipped.append({"id": image_id, "reason": "找不到組圖結果"})
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        files.append(candidate)
    return files, skipped


def _upload_search_terms(message: str, filters: dict[str, object]) -> list[str]:
    terms: list[str] = []
    for key in ("countries", "regions", "features"):
        values = filters.get(key)
        if isinstance(values, list):
            terms.extend(str(value).strip() for value in values if str(value).strip())
    months = filters.get("months")
    if isinstance(months, list):
        for month in months:
            text = str(month).strip()
            if text:
                terms.extend([text, f"{text}月"])
    duration = filters.get("duration_days")
    if duration:
        terms.extend([str(duration), f"{duration}天"])
    return terms


def _upload_annotation_values(image: dict[str, object]) -> list[str]:
    values: list[str] = []
    override_values = [str(value) for value in image.get("ocr_tags_override") or []]
    system_tags_overridden = bool(override_values)
    for value in override_values:
        if str(value) == SYSTEM_TAGS_CLEARED_SENTINEL:
            continue
        values.append(str(value))
    if not system_tags_overridden:
        for tag in image.get("system_tags") or []:
            if isinstance(tag, dict):
                values.append(str(tag.get("tag") or ""))
            else:
                values.append(str(tag))
    for tag in image.get("manual_tags") or []:
        if isinstance(tag, dict):
            values.append(str(tag.get("tag") or ""))
        else:
            values.append(str(tag))
    for key in ("reference_text", "manual_note", "display_name", "original_filename", "ocr_text", "search_text"):
        values.append(str(image.get(key) or ""))
    return [value.strip() for value in values if value and value.strip()]


def _upload_image_matches_query(image: dict[str, object], message: str, terms: list[str]) -> bool:
    values = _upload_annotation_values(image)
    haystack = " ".join(values).lower()
    if not haystack:
        return False
    if terms:
        return all(term.lower() in haystack for term in terms)

    lowered_message = message.lower()
    for value in values:
        lowered_value = value.lower()
        if 1 < len(lowered_value) <= 60 and lowered_value in lowered_message:
            return True

    for token in re.split(r"[\s,，、。！？!?\[\]（）()]+", message):
        token = token.strip().lower()
        if len(token) >= 2 and token in haystack:
            return True
    return False


def _manual_tags_for_images(image_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    ids = [int(image_id) for image_id in image_ids if image_id]
    if not ids:
        return {}

    return {image_id: list_manual_tags(image_id) for image_id in ids}


def _upload_image_record(image_id: int) -> tuple[dict[str, object], dict[str, object]] | None:
    with open_db(CATALOG_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT i.*, f.folder_slug, f.display_name AS folder_display_name,
                   f.note AS folder_note, f.source AS folder_source,
                   f.status AS folder_status, f.current_step AS folder_current_step,
                   f.step_statuses AS folder_step_statuses, f.image_count AS folder_image_count,
                   f.line_groups AS folder_line_groups, f.captured_at AS folder_captured_at,
                   f.job_id AS folder_job_id, f.archived_at AS folder_archived_at,
                   f.archived_by AS folder_archived_by, f.delete_after AS folder_delete_after,
                   f.created_at AS folder_created_at, f.updated_at AS folder_updated_at
            FROM uploaded_images i
            JOIN upload_folders f ON f.id = i.folder_id
            WHERE i.id = ?
            """,
            (image_id,),
        ).fetchone()
    if row is None:
        return None
    image = {
        "id": row["id"],
        "folder_id": row["folder_id"],
        "original_filename": row["original_filename"],
        "stored_path": row["stored_path"],
        "sha256": row["sha256"],
        "display_name": row["display_name"],
        "ocr_tags_override": _json_list(row["ocr_tags_override"]),
        "reference_text": row["reference_text"],
        "manual_note": row["manual_note"],
        "archived_at": row["archived_at"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
        "uploaded_at": row["uploaded_at"],
        "ocr_status": row["ocr_status"],
        "compose_status": row["compose_status"],
    }
    folder = {
        "id": row["folder_id"],
        "folder_slug": row["folder_slug"],
        "display_name": row["folder_display_name"],
        "note": row["folder_note"],
        "source": row["folder_source"],
        "status": row["folder_status"],
        "current_step": row["folder_current_step"],
        "step_statuses": _json_object(row["folder_step_statuses"]),
        "image_count": row["folder_image_count"],
        "line_groups": _json_list(row["folder_line_groups"]),
        "captured_at": row["folder_captured_at"],
        "job_id": row["folder_job_id"],
        "archived_at": row["folder_archived_at"],
        "archived_by": row["folder_archived_by"],
        "delete_after": row["folder_delete_after"],
        "created_at": row["folder_created_at"],
        "updated_at": row["folder_updated_at"],
        "target_id": row["folder_slug"],
    }
    return image, folder


def _refresh_upload_search_index_for_image(image_id: int) -> None:
    record = _upload_image_record(image_id)
    if record is None:
        delete_image_search_index(image_id)
        return
    image, folder = record
    if image.get("archived_at") or folder.get("archived_at"):
        delete_image_search_index(image_id)
        return

    current_path = _find_current_image_path(image, folder)
    current_payload = _sidecar_payload_for_image(current_path)
    sidecar_payloads = [current_payload] if current_payload else []
    fields = _merge_sidecar_query_fields(sidecar_payloads)
    system_tags = _merge_system_tags([_sidecar_system_tags(payload) for payload in sidecar_payloads])
    override_values = _normalize_ocr_tag_values(image.get("ocr_tags_override"))
    system_tags_overridden = bool(override_values)
    system_tag_values = [] if system_tags_overridden else [
        str(tag.get("tag") or "") for tag in system_tags if isinstance(tag, dict)
    ]
    override_tags = [
        str(tag)
        for tag in override_values
        if str(tag).strip() and str(tag) != SYSTEM_TAGS_CLEARED_SENTINEL
    ]
    manual_tags = _manual_tags_for_images([image_id]).get(image_id, [])
    manual_tag_values = [str(tag.get("tag") or "") for tag in manual_tags if isinstance(tag, dict)]
    sidecar_text = []
    for payload in sidecar_payloads:
        for value in _sidecar_text_values(payload):
            if value not in sidecar_text:
                sidecar_text.append(value)
    branded_path = ""
    if current_path is not None:
        current_rel = current_path.relative_to(PROJECT_ROOT).as_posix()
        by_source, by_hash = _branded_image_lookup(folder)
        branded = by_source.get(current_rel) or by_hash.get(str(image.get("sha256") or ""))
        if branded is not None:
            branded_path = branded.relative_to(PROJECT_ROOT).as_posix()
    else:
        current_rel = str(image.get("stored_path") or "")

    features = sorted({tag for tag in [*override_tags, *system_tag_values, *manual_tag_values] if tag})
    search_parts = [
        str(folder.get("display_name") or ""),
        str(image.get("display_name") or ""),
        str(image.get("original_filename") or ""),
        str(image.get("reference_text") or ""),
        str(image.get("manual_note") or ""),
        *features,
        *[str(value) for value in fields.get("countries") or []],
        *[str(value) for value in fields.get("regions") or []],
        *[f"{value}月" for value in fields.get("months") or []],
        *sidecar_text,
    ]
    upsert_image_search_index(
        image_id,
        folder_id=int(folder["id"]),
        search_text=" ".join(part for part in search_parts if part).strip(),
        raw_text=" ".join(sidecar_text),
        countries=list(fields.get("countries") or []),
        regions=list(fields.get("regions") or []),
        months=list(fields.get("months") or []),
        features=features,
        price_from=fields.get("price_from"),
        duration_days=fields.get("duration_days"),
        sidecar_path=branded_path or current_rel,
        image_path=current_rel,
        branded_path=branded_path,
        source_time=str(image.get("uploaded_at") or ""),
    )


def _refresh_upload_search_index_for_same_sha_images(image_id: int) -> None:
    image_ids = same_sha_image_ids(image_id) or [image_id]
    for related_image_id in image_ids:
        _refresh_upload_search_index_for_image(related_image_id)


def _ensure_upload_search_index_current() -> None:
    for image_id in missing_search_index_image_ids():
        _refresh_upload_search_index_for_image(image_id)


def _image_id_for_manual_tag(tag_id: int) -> int | None:
    with open_db(CATALOG_DB_PATH) as conn:
        row = conn.execute("SELECT image_id FROM manual_tags WHERE id = ?", (tag_id,)).fetchone()
    return int(row[0]) if row else None


def _upload_image_query_item(folder: dict[str, object], image: dict[str, object]) -> dict[str, object]:
    override_values = [str(tag) for tag in image.get("ocr_tags_override") or []]
    system_tags_overridden = bool(override_values)
    system_tags = [] if system_tags_overridden else [
        str(tag.get("tag") or "") for tag in image.get("system_tags") or [] if isinstance(tag, dict)
    ]
    override_tags = [
        str(tag)
        for tag in override_values
        if str(tag).strip() and str(tag) != SYSTEM_TAGS_CLEARED_SENTINEL
    ]
    manual_tags = [str(tag.get("tag") or "") for tag in image.get("manual_tags") or [] if isinstance(tag, dict)]
    features = sorted({tag for tag in [*override_tags, *system_tags, *manual_tags] if tag})
    media_path = (
        image.get("branded_path")
        or image.get("current_path")
        or image.get("stored_path")
        or image.get("image_path")
    )
    return {
        "image_id": image.get("id"),
        "folder_id": folder.get("id"),
        "sidecar_path": media_path,
        "image_path": image.get("current_path") or image.get("stored_path") or media_path,
        "branded_path": image.get("branded_path") or image.get("current_path") or media_path,
        "countries": image.get("countries") or [],
        "regions": image.get("regions") or [],
        "months": image.get("months") or [],
        "features": features,
        "duration_days": image.get("duration_days"),
        "price_from": image.get("price_from"),
        "group_name": folder.get("display_name"),
        "target_id": folder.get("folder_slug"),
        "source_time": image.get("uploaded_at"),
        "indexed_at": image.get("updated_at") or image.get("uploaded_at"),
        "manual_tags": image.get("manual_tags") or [],
        "reference_text": image.get("reference_text") or "",
        "ocr_tags_override": image.get("ocr_tags_override") or [],
        "raw_text": image.get("ocr_text") or "",
        "search_text": image.get("search_text") or image.get("ocr_text") or "",
        "source": "upload_catalog",
    }


def _query_upload_catalog(message: str, filters: dict[str, object], *, limit: int) -> list[dict[str, object]]:
    _ensure_upload_search_index_current()
    terms = _upload_search_terms(message, filters)
    return query_image_search_index(
        query_text=message,
        terms=terms,
        countries=list(filters.get("countries") or []),
        regions=list(filters.get("regions") or []),
        months=list(filters.get("months") or []),
        features=list(filters.get("features") or []),
        price_min=filters.get("price_min"),
        price_max=filters.get("price_max"),
        duration_days=filters.get("duration_days"),
        limit=limit,
    )


def _annotation_search_values(annotation: dict[str, object]) -> list[str]:
    values: list[str] = []
    for key in ("manual_tags", "ocr_tags_override"):
        for value in _tag_text_values(annotation.get(key)):
            values.append(value)
    for key in ("reference_text", "manual_note"):
        text = str(annotation.get(key) or "").strip()
        if text:
            values.append(text)
    return values


def _annotation_query_terms(message: str, filters: dict[str, object]) -> list[str]:
    text = str(message or "").lower()
    ignored: list[str] = []
    for key in ("countries", "regions"):
        values = filters.get(key)
        if isinstance(values, list):
            ignored.extend(str(value).strip().lower() for value in values if str(value).strip())
    months = filters.get("months")
    if isinstance(months, list):
        for month in months:
            value = str(month).strip().lower()
            if value:
                ignored.extend([value, f"{value}月"])
    duration = filters.get("duration_days")
    if duration:
        value = str(duration).strip().lower()
        ignored.extend([value, f"{value}天", f"{value}日"])

    for value in sorted({term for term in ignored if term}, key=len, reverse=True):
        text = text.replace(value, " ")
    return [
        term.strip()
        for term in re.split(r"[\s,，、/|]+", text)
        if term.strip()
    ]


def _annotation_matches_query(annotation: dict[str, object], message: str, filters: dict[str, object]) -> bool:
    values = _annotation_search_values(annotation)
    if not values:
        return False
    haystack = " ".join(values).lower()
    terms = _annotation_query_terms(message, filters)
    if terms:
        return all(term in haystack for term in terms)
    lowered_message = message.lower().strip()
    return bool(lowered_message and lowered_message in haystack)


def _csv_values(value: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in str(value or "").split(","):
        text = token.strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _line_annotation_item(row: sqlite3.Row | dict[str, object], annotation: dict[str, object]) -> dict[str, object]:
    override_tags = [
        value
        for value in _tag_text_values(annotation.get("ocr_tags_override"))
        if value != SYSTEM_TAGS_CLEARED_SENTINEL
    ]
    manual_tags = _manual_tag_values(annotation.get("manual_tags"))
    features = sorted({*override_tags, *manual_tags, *_csv_values(row["features_csv"])})
    return {
        "sidecar_path": row["sidecar_path"],
        "image_path": row["image_path"],
        "branded_path": row["branded_path"] or row["image_path"],
        "target_id": row["target_id"],
        "group_name": row["group_name"],
        "countries": _csv_values(row["country_csv"]),
        "regions": _csv_values(row["region_csv"]),
        "months": [int(value) for value in _csv_values(row["months_csv"]) if value.isdigit()],
        "price_from": row["price_from"],
        "airlines": _csv_values(row["airline_csv"]),
        "duration_days": row["duration_days"],
        "features": features,
        "source_time": row["source_time"],
        "indexed_at": row["indexed_at"],
        "manual_tags": [{"id": f"line-{index}", "tag": value} for index, value in enumerate(manual_tags, 1)],
        "reference_text": str(annotation.get("reference_text") or ""),
        "ocr_tags_override": override_tags,
        "source": "line",
    }


def _query_line_annotation_results(message: str, filters: dict[str, object], *, limit: int) -> list[dict[str, object]]:
    annotations = _read_item_annotations()
    matched = {
        key.removeprefix("line:"): annotation
        for key, annotation in annotations.items()
        if key.startswith("line:") and _annotation_matches_query(annotation, message, filters)
    }
    if not matched:
        return []
    sidecars = list(matched.keys())[:max(1, limit * 3)]
    placeholders = ",".join("?" for _ in sidecars)
    clauses = [f"sidecar_path IN ({placeholders})"]
    params: list[object] = list(sidecars)

    def add_csv_filter(column: str, values: object) -> None:
        if not isinstance(values, list):
            return
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if not cleaned:
            return
        clauses.append("(" + " OR ".join(f"{column} LIKE ?" for _ in cleaned) + ")")
        params.extend(f"%,{value},%" for value in cleaned)

    add_csv_filter("country_csv", filters.get("countries"))
    add_csv_filter("region_csv", filters.get("regions"))
    add_csv_filter("months_csv", filters.get("months"))
    duration = filters.get("duration_days")
    if duration:
        clauses.append("duration_days = ?")
        params.append(duration)
    price_min = filters.get("price_min")
    if price_min is not None:
        clauses.append("price_from >= ?")
        params.append(price_min)
    price_max = filters.get("price_max")
    if price_max is not None:
        clauses.append("price_from <= ?")
        params.append(price_max)

    try:
        with open_db(DEFAULT_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                f"""
                SELECT *
                FROM itineraries
                WHERE {" AND ".join(clauses)}
                ORDER BY indexed_at DESC, source_time DESC, rowid DESC
                LIMIT ?
                """,
                [*params, limit],
            )
            try:
                rows = [dict(row) for row in cursor.fetchall()]
            finally:
                cursor.close()
    except sqlite3.Error:
        return []
    return [_line_annotation_item(row, matched[str(row["sidecar_path"])]) for row in rows]


def _merge_line_annotation_results(payload: dict, message: str, filters: dict[str, object], *, limit: int) -> dict:
    line_items = _query_line_annotation_results(message, filters, limit=limit)
    if not line_items:
        return payload

    copy = dict(payload)
    items = list(copy.get("items") or [])
    seen = {
        str(item.get("sidecar_path") or item.get("branded_path") or item.get("image_path") or "")
        for item in items
    }
    for item in line_items:
        key = str(item.get("sidecar_path") or item.get("branded_path") or item.get("image_path") or "")
        if key and key in seen:
            continue
        seen.add(key)
        items.append(item)
    copy["items"] = items[:limit]
    copy["count"] = len(copy["items"])
    return copy


def _merge_upload_catalog_results(payload: dict, message: str, filters: dict[str, object], *, limit: int) -> dict:
    upload_items = _query_upload_catalog(message, filters, limit=limit)
    if not upload_items:
        return payload

    copy = dict(payload)
    items = list(copy.get("items") or [])
    seen = {
        str(item.get("sidecar_path") or item.get("branded_path") or item.get("image_path") or "")
        for item in items
    }
    for item in upload_items:
        key = str(item.get("sidecar_path") or item.get("branded_path") or item.get("image_path") or "")
        if key and key in seen:
            continue
        seen.add(key)
        items.append(item)
    copy["items"] = items[:limit]
    copy["count"] = len(copy["items"])
    return copy


def _upload_slug_for_item(item: dict[str, object]) -> str:
    for key in ("target_id", "group_name"):
        value = str(item.get(key) or "").strip()
        if value.startswith("upload_"):
            return value
    return ""


def _archived_upload_folder_slugs(slugs: set[str]) -> set[str]:
    if not slugs:
        return set()
    placeholders = ",".join("?" for _ in slugs)
    try:
        with open_db(CATALOG_DB_PATH) as conn:
            rows = conn.execute(
                f"""
                SELECT folder_slug
                FROM upload_folders
                WHERE archived_at IS NOT NULL
                  AND folder_slug IN ({placeholders})
                """,
                sorted(slugs),
            ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]) for row in rows}


def _filter_archived_upload_items(payload: dict) -> dict:
    items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    group_items = [
        item
        for group in payload.get("groups") or []
        if isinstance(group, dict)
        for item in group.get("items") or []
        if isinstance(item, dict)
    ]
    slugs = {_upload_slug_for_item(item) for item in [*items, *group_items]}
    archived_slugs = _archived_upload_folder_slugs({slug for slug in slugs if slug})
    if not archived_slugs:
        return payload

    def keep(item: dict[str, object]) -> bool:
        return _upload_slug_for_item(item) not in archived_slugs

    copy = dict(payload)
    if isinstance(copy.get("items"), list):
        copy["items"] = [item for item in items if keep(item)]
        copy["count"] = len(copy["items"])
    if isinstance(copy.get("groups"), list):
        groups = []
        for group in copy.get("groups") or []:
            if not isinstance(group, dict):
                continue
            group_copy = dict(group)
            filtered_items = [
                item
                for item in group.get("items") or []
                if isinstance(item, dict) and keep(item)
            ]
            if filtered_items:
                group_copy["items"] = filtered_items
                group_copy["count"] = len(filtered_items)
                groups.append(group_copy)
        copy["groups"] = groups
        copy["count"] = len(groups)
    return copy


def _item_path_values(item: dict[str, object]) -> list[str]:
    values = []
    for key in ("sidecar_path", "image_path", "branded_path"):
        value = str(item.get(key) or "").strip()
        if value:
            values.append(value)
    return values


def _batched_lookup_values(values: list[object], size: int = 250) -> list[list[object]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _image_sha_lookup(items: list[dict[str, object]]) -> dict[str, str]:
    image_ids = sorted({
        int(item["image_id"])
        for item in items
        if str(item.get("image_id") or "").isdigit()
    })
    paths = sorted({path for item in items for path in _item_path_values(item)})
    lookup: dict[str, str] = {}

    if image_ids or paths:
        try:
            with open_db(CATALOG_DB_PATH) as conn:
                rows = []
                for batch in _batched_lookup_values(image_ids):
                    placeholders = ",".join("?" for _ in batch)
                    rows.extend(conn.execute(
                        f"""
                        SELECT i.id, i.sha256, s.sidecar_path, s.image_path, s.branded_path
                        FROM uploaded_images i
                        LEFT JOIN uploaded_image_search_index s ON s.image_id = i.id
                        WHERE i.id IN ({placeholders})
                        """,
                        batch,
                    ).fetchall())
                for batch in _batched_lookup_values(paths):
                    placeholders = ",".join("?" for _ in batch)
                    rows.extend(conn.execute(
                        f"""
                        SELECT i.id, i.sha256, s.sidecar_path, s.image_path, s.branded_path
                        FROM uploaded_images i
                        LEFT JOIN uploaded_image_search_index s ON s.image_id = i.id
                        WHERE s.sidecar_path IN ({placeholders})
                           OR s.image_path IN ({placeholders})
                           OR s.branded_path IN ({placeholders})
                        """,
                        [*batch, *batch, *batch],
                    ).fetchall())
        except sqlite3.Error:
            rows = []
        for row in rows:
            sha = str(row[1] or "").strip()
            if not sha:
                continue
            lookup[f"image_id:{row[0]}"] = sha
            for value in (row[2], row[3], row[4]):
                text = str(value or "").strip()
                if text:
                    lookup[f"path:{text}"] = sha

    if paths:
        try:
            with open_db(DEFAULT_DB_PATH) as conn:
                rows = []
                for batch in _batched_lookup_values(paths):
                    placeholders = ",".join("?" for _ in batch)
                    rows.extend(conn.execute(
                        f"""
                        SELECT image_sha256, sidecar_path, image_path, branded_path
                        FROM itineraries
                        WHERE sidecar_path IN ({placeholders})
                           OR image_path IN ({placeholders})
                           OR branded_path IN ({placeholders})
                        """,
                        [*batch, *batch, *batch],
                    ).fetchall())
        except sqlite3.Error:
            rows = []
        for row in rows:
            sha = str(row[0] or "").strip()
            if not sha:
                continue
            for value in (row[1], row[2], row[3]):
                text = str(value or "").strip()
                if text:
                    lookup[f"path:{text}"] = sha

    return lookup


def _image_dedupe_key(item: dict[str, object], sha_lookup: dict[str, str]) -> str:
    for key in ("image_sha256", "sha256"):
        value = str(item.get(key) or "").strip()
        if value:
            return f"sha:{value}"
    image_id = str(item.get("image_id") or "").strip()
    if image_id:
        sha = sha_lookup.get(f"image_id:{image_id}")
        if sha:
            return f"sha:{sha}"
    for path in _item_path_values(item):
        sha = sha_lookup.get(f"path:{path}")
        if sha:
            return f"sha:{sha}"
    path = next(iter(_item_path_values(item)), "")
    return f"path:{path}" if path else ""


def _dedupe_payload_images(payload: dict) -> dict:
    """Final safety dedupe for payloads merged across travel and upload sources."""
    items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    if len(items) < 2:
        return payload
    needs_lookup = any(
        not str(item.get("image_sha256") or item.get("sha256") or "").strip()
        for item in items
    )
    sha_lookup = _image_sha_lookup(items) if needs_lookup else {}
    seen: set[str] = set()
    deduped = []
    for item in items:
        key = _image_dedupe_key(item, sha_lookup)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(item)
    if len(deduped) == len(items):
        return payload
    copy = dict(payload)
    copy["items"] = deduped
    copy["count"] = len(deduped)
    return copy


def _chat_payload(message: str, limit: int, *, include_archived: bool = False) -> dict:
    lower = message.lower()
    # Order matters: specific intent (latest/duplicates) beats general state queries (status).
    if any(token in message for token in ["最新", "今日", "今天", "新組合", "新 DM", "新DM"]) or "latest" in lower:
        is_today = any(token in message for token in ["今日", "今天"])
        is_combo = any(token in message for token in ["組合", "組圖", "新組合"])
        if is_today:
            payload = query_latest_results(
                today=True,
                composed_only=is_combo,
                limit=max(limit, 300),
                include_archived=include_archived,
            )
        else:
            payload = query_latest_results(limit=max(limit * 3, limit), include_archived=include_archived)
            payload = _prioritize_priced_items(payload, limit)
        payload = _dedupe_payload_images(_filter_archived_upload_items(payload))
        payload = _with_media_urls(payload)
        payload["kind"] = "latest"
        payload["message"] = (
            f"Agent 找到 {payload.get('count', 0)} 份今日組圖 DM。"
            if is_today and is_combo
            else f"Agent 找到 {payload.get('count', 0)} 份最新旅遊 DM。"
        )
        return payload

    if any(token in message for token in ["重複", "相同", "去重"]) or "duplicate" in lower:
        payload = _filter_archived_upload_items(check_duplicates(limit_groups=min(limit, 30), include_same_source=True))
        payload = _with_media_urls(payload)
        payload["kind"] = "duplicates"
        payload["message"] = f"Agent 找到 {payload.get('count', 0)} 組可能重複圖片。"
        return payload

    if any(token in message for token in ["狀態", "進度", "處理狀況", "資料庫", "db"]) or "status" in lower:
        payload = _status_with_manual_job()
        payload["kind"] = "status"
        payload["message"] = "Agent 狀態已讀取。"
        return payload

    filters = _parse_search(message)
    has_filters = _has_meaningful_search_filters(filters)
    if has_filters:
        payload = query_itineraries(
            countries=filters["countries"],
            regions=filters["regions"],
            months=filters["months"],
            features=filters["features"],
            price_min=filters["price_min"],
            price_max=filters["price_max"],
            duration_days=filters["duration_days"],
            limit=limit,
            include_archived=include_archived,
        )
    else:
        payload = {"count": 0, "items": [], "filters": {}, "warning": "沒有足夠條件可查詢。"}

    payload = _merge_upload_catalog_results(payload, message, filters, limit=limit)
    payload = _merge_line_annotation_results(payload, message, filters, limit=limit)
    payload = _dedupe_payload_images(_filter_archived_upload_items(payload))
    payload = _with_media_urls(payload)
    payload["kind"] = "query"
    payload["query"] = message
    count = payload.get("count", 0)
    payload["message"] = (
        f"沒有找到「{message}」的旅遊 DM。"
        if count == 0
        else f"Agent 查詢「{message}」找到 {count} 份旅遊 DM。"
    )
    return payload


def _launch_upload_pipeline(folder: dict[str, object], *, trigger_source: str = "upload") -> dict[str, object]:
    if not RUN_UPLOAD_SCRIPT.is_file():
        return {"ok": False, "error": "upload runner script missing"}
    update_folder_status(
        int(folder["id"]),
        status="running",
        current_step="ocr",
        step_statuses={"upload": "success", "ocr": "pending", "compose": "pending", "index": "pending"},
    )
    process = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(RUN_UPLOAD_SCRIPT),
            "-Target",
            str(folder["folder_slug"]),
            "-FolderId",
            str(folder["id"]),
            "-TriggerSource",
            trigger_source,
        ],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    # Without this watcher, queued upload jobs would only drain when the next
    # browser GET /api/uploads/* fired _start_pending_upload_pipeline_if_idle.
    # Closing the tab while a job was running could strand later uploads.
    threading.Thread(target=_watch_upload_pipeline, args=(process,), daemon=True).start()
    return {"ok": True, "started": True, "pid": process.pid}


def _watch_upload_pipeline(process: subprocess.Popen) -> None:
    try:
        process.wait()
    except Exception:
        pass
    try:
        _start_pending_upload_pipeline_if_idle()
    except Exception:
        pass


def _start_pending_upload_pipeline_if_idle() -> dict[str, object] | None:
    if _upload_pipeline_is_busy():
        return None
    with PENDING_UPLOAD_LOCK:
        jobs = _read_pending_upload_jobs()
        while jobs:
            job = jobs.pop(0)
            _write_pending_upload_jobs(jobs)
            folder = get_folder(int(job.get("folder_id") or 0))
            if not folder:
                continue
            result = _launch_upload_pipeline(folder, trigger_source=str(job.get("trigger_source") or "upload"))
            return {"job": job, "result": result}
    return None


class Handler(SimpleHTTPRequestHandler):
    server_version = "AgentTravelInterface/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def guess_type(self, path):
        # SimpleHTTPRequestHandler omits charset on text/* responses, leaving
        # downstream middleboxes (Cloudflare Tunnel in particular) free to
        # serve UTF-8-encoded JS/HTML/CSS with a default Big5 fallback on
        # zh-TW clients, garbling every Chinese label in the bundled UI.
        mime = super().guess_type(path)
        if mime in {
            "text/html",
            "text/javascript",
            "application/javascript",
            "text/css",
            "text/plain",
            "application/json",
            "image/svg+xml",
        }:
            return f"{mime}; charset=utf-8"
        return mime

    def end_headers(self) -> None:
        # Clipboard image writes are controlled by browser security policy.
        # The user must still grant/trigger permission, but this header makes
        # the app's intent explicit through reverse proxies and browser checks.
        self.send_header("Permissions-Policy", "clipboard-write=(self), clipboard-read=(self)")
        request_path = urlparse(self.path).path
        if request_path == "/" or request_path.startswith("/assets/") or request_path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _is_secure_request(self) -> bool:
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").lower()
        forwarded_ssl = self.headers.get("X-Forwarded-Ssl", "").lower()
        return forwarded_proto == "https" or forwarded_ssl == "on"

    def _auth_cookie_header(self, token: str, *, max_age: int) -> str:
        parts = [
            f"{AUTH_COOKIE_NAME}={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={max_age}",
        ]
        if self._is_secure_request():
            parts.append("Secure")
        return "; ".join(parts)

    def _auth_session(self) -> dict[str, object] | None:
        token = _cookie_value(self.headers.get("Cookie", ""), AUTH_COOKIE_NAME)
        return _decode_auth_session(token) if token else None

    def _is_authenticated(self) -> bool:
        return self._auth_session() is not None

    def _require_auth(self) -> bool:
        if self._is_authenticated():
            return True
        self._json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        return False

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    def _json_auth_response(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        cookie: str | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _handle_auth_session(self) -> None:
        session = self._auth_session()
        if not session:
            self._json_auth_response({"ok": False, "authenticated": False})
            return
        self._json_auth_response({
            "ok": True,
            "authenticated": True,
            "username": session["username"],
            "expires_at": session["expires_at"],
        })

    def _handle_auth_login(self) -> None:
        try:
            data = self._read_json_body()
            username = str(data.get("username") or "").strip()
            password = str(data.get("password") or "")
            valid = hmac.compare_digest(username, AUTH_USERNAME) and hmac.compare_digest(password, AUTH_PASSWORD)
            if not valid:
                self._json_auth_response(
                    {"ok": False, "error": "帳號或密碼不正確"},
                    HTTPStatus.UNAUTHORIZED,
                )
                return

            remember = bool(data.get("remember"))
            ttl = AUTH_SESSION_TTL_REMEMBER_SECONDS if remember else AUTH_SESSION_TTL_SECONDS
            token = _encode_auth_session(username, ttl_seconds=ttl)
            cookie = self._auth_cookie_header(token, max_age=ttl)
            self._json_auth_response(
                {"ok": True, "authenticated": True, "username": username, "remember": remember},
                cookie=cookie,
            )
        except Exception as exc:
            self._json_auth_response(
                {"ok": False, "error": str(exc), "type": exc.__class__.__name__},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _handle_auth_logout(self) -> None:
        cookie = self._auth_cookie_header("", max_age=0)
        self._json_auth_response({"ok": True, "authenticated": False}, cookie=cookie)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/session":
            self._handle_auth_session()
            return
        if parsed.path.startswith("/api/uploads/") or parsed.path == "/api/uploads/folders":
            if not self._require_auth():
                return
            self._handle_uploads_get(parsed.path, parse_qs(parsed.query))
            return
        if parsed.path.startswith("/api/openclaw/"):
            if not self._require_auth():
                return
            self._handle_api(parsed.path, parse_qs(parsed.query))
            return
        if parsed.path == "/media/thumbnail":
            if not self._require_auth():
                return
            self._handle_media(parse_qs(parsed.query), thumbnail=True)
            return
        if parsed.path == "/media":
            if not self._require_auth():
                return
            self._handle_media(parse_qs(parsed.query))
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/login":
            self._handle_auth_login()
            return
        if parsed.path == "/api/auth/logout":
            self._handle_auth_logout()
            return
        if parsed.path.startswith("/api/uploads/") or parsed.path == "/api/uploads/folders":
            if not self._require_auth():
                return
            self._handle_uploads_post(parsed.path)
            return
        openclaw_path = parsed.path.rstrip("/") if parsed.path.startswith("/api/openclaw/") else parsed.path
        if parsed.path.startswith("/api/openclaw/") and not self._require_auth():
            return
        if openclaw_path == "/api/openclaw/settings":
            self._handle_settings_update()
            return
        if openclaw_path == "/api/openclaw/item-detail":
            self._handle_item_detail_update()
            return
        if openclaw_path == "/api/openclaw/chat":
            self._handle_chat()
            return
        if openclaw_path == "/api/openclaw/clipboard":
            self._handle_clipboard()
            return
        if openclaw_path == "/api/openclaw/download":
            self._handle_download()
            return
        if openclaw_path == "/api/openclaw/duplicates/review":
            self._handle_duplicate_review()
            return
        if openclaw_path == "/api/openclaw/run":
            self._handle_run()
            return
        self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/uploads/") and not self._require_auth():
            return
        if parsed.path.startswith("/api/uploads/"):
            self._handle_uploads_delete(parsed.path)
            return
        self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/uploads/") and not self._require_auth():
            return
        if parsed.path.startswith("/api/uploads/"):
            self._handle_uploads_patch(parsed.path)
            return
        self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        # Central server-side trace for every 5xx. Called from within handler
        # `except` blocks, so traceback.format_exc() captures the live exception.
        if int(status) >= 500:
            if sys.exc_info()[0] is not None:
                logger.error("%s %s -> %s\n%s", self.command, self.path, payload, traceback.format_exc())
            else:
                logger.error("%s %s -> %s", self.command, self.path, payload)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_api(self, path: str, params: dict[str, list[str]]) -> None:
        try:
            path = path.rstrip("/")
            if path == "/api/openclaw/status":
                self._json(_status_with_manual_job(target_id=_first(params, "target") or None))
                return

            if path == "/api/openclaw/settings":
                self._json({"ok": True, "settings": _read_openclaw_settings()})
                return

            if path == "/api/openclaw/item-detail":
                detail = _query_item_detail(params)
                if detail is None:
                    self._json({"ok": False, "error": "item not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._json({"ok": True, "detail": detail})
                return

            if path == "/api/openclaw/run":
                body = json.dumps({"ok": False, "error": "method not allowed", "allow": ["POST"]}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header("Allow", "POST")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if path == "/api/openclaw/latest":
                today = _first(params, "today").lower() in {"1", "true", "yes"}
                composed_only = _first(params, "composed_only").lower() in {"1", "true", "yes"}
                include_archived = _first(params, "include_archived").lower() in {"1", "true", "yes"}
                payload = query_latest_results(
                    hours=_as_int(_first(params, "hours"), None),
                    today=today,
                    composed_only=composed_only,
                    target_id=_first(params, "target") or None,
                    limit=_as_int(_first(params, "limit", "12"), 12) or 12,
                    include_archived=include_archived,
                )
                if today or composed_only:
                    threading.Thread(
                        target=_prewarm_payload_thumbnails,
                        args=(payload,),
                        kwargs={"limit": 80},
                        daemon=True,
                    ).start()
                self._json(_with_media_urls(_dedupe_payload_images(_filter_archived_upload_items(payload))))
                return

            if path == "/api/openclaw/download":
                media_ids = params.get("media_id") or params.get("media_ids") or []
                files = _media_ids_to_files(media_ids)
                self._send_download_zip(files)
                return

            if path == "/api/openclaw/search":
                q = _first(params, "q").strip()
                include_archived = _first(params, "include_archived").lower() in {"1", "true", "yes"}
                payload = _chat_payload(
                    q,
                    _as_int(_first(params, "limit", "12"), 12) or 12,
                    include_archived=include_archived,
                )
                self._json(payload)
                return

            if path == "/api/openclaw/duplicates":
                limit = _as_int(_first(params, "limit", "20"), 20) or 20
                include_same_source = _first(params, "include_same_source", "1").lower() in {"1", "true", "yes"}
                include_reviewed = _first(params, "include_reviewed").lower() in {"1", "true", "yes"}
                self._json(_with_media_urls(check_duplicates(
                    limit_groups=limit,
                    include_same_source=include_same_source,
                    include_reviewed=include_reviewed,
                )))
                return

            self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_settings_update(self) -> None:
        try:
            data = self._read_json_body()
            settings = {}
            if "line_auto_enabled" in data:
                settings["line_auto_enabled"] = bool(data.get("line_auto_enabled"))
            self._json({"ok": True, "settings": _write_openclaw_settings(settings)})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_item_detail_update(self) -> None:
        try:
            data = self._read_json_body()
            source_kind = str(data.get("source_kind") or data.get("source") or "").strip()
            image_id = _as_int(data.get("image_id"), None)

            if source_kind == "upload" or image_id is not None:
                if image_id is None:
                    self._json({"ok": False, "error": "image_id is required"}, HTTPStatus.BAD_REQUEST)
                    return
                detail = _upload_item_detail(int(image_id))
                if detail is None:
                    self._json({"ok": False, "error": "item not found"}, HTTPStatus.NOT_FOUND)
                    return
                override = _system_tag_override_for_update(
                    _tag_text_values(detail.get("source_system_tags")),
                    data.get("system_tags"),
                )
                updated = update_image_metadata(
                    int(image_id),
                    ocr_tags_override=override,
                    reference_text=str(data.get("reference_text") or "") if "reference_text" in data else None,
                    manual_note=str(data.get("manual_note") or "") if "manual_note" in data else None,
                    updated_by="web",
                )
                if not updated:
                    self._json({"ok": False, "error": "item not found"}, HTTPStatus.NOT_FOUND)
                    return
                if "manual_tags" in data:
                    _replace_upload_manual_tags(int(image_id), _manual_tag_values(data.get("manual_tags")))
                _refresh_upload_search_index_for_same_sha_images(int(image_id))
                self._json({"ok": True, "detail": _upload_item_detail(int(image_id))})
                return

            sidecar_path = str(data.get("sidecar_path") or data.get("source_key") or "").strip()
            detail = _line_item_detail(sidecar_path)
            if detail is None:
                self._json({"ok": False, "error": "item not found"}, HTTPStatus.NOT_FOUND)
                return
            override = _system_tag_override_for_update(
                _tag_text_values(detail.get("source_system_tags")),
                data.get("system_tags"),
            )
            patch = {
                "manual_tags": _manual_tag_values(data.get("manual_tags")),
                "reference_text": str(data.get("reference_text") or "") if "reference_text" in data else detail.get("reference_text", ""),
                "manual_note": str(data.get("manual_note") or "") if "manual_note" in data else detail.get("manual_note", ""),
            }
            if override is not None:
                patch["ocr_tags_override"] = override
            _save_item_annotation("line", detail["sidecar_path"], patch)
            self._json({"ok": True, "detail": _line_item_detail(str(detail["sidecar_path"]))})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _start_upload_pipeline(self, folder: dict[str, object], *, trigger_source: str = "upload") -> dict[str, object]:
        latest = _latest_job_snapshot()
        current = _manual_job_snapshot()
        if _upload_pipeline_is_busy():
            _queue_pending_upload_job(folder, trigger_source=trigger_source)
            return {
                "ok": True,
                "started": False,
                "queued": True,
                "job": latest or current,
                "message": "pipeline is busy; upload processing has been queued",
            }
        return _launch_upload_pipeline(folder, trigger_source=trigger_source)

    def _handle_uploads_get(self, path: str, params: dict[str, list[str]]) -> None:
        try:
            _start_pending_upload_pipeline_if_idle()
            if path == "/api/uploads/folders":
                limit = _as_int(_first(params, "limit", "50"), 50) or 50
                folders = [_folder_summary(folder) for folder in list_folders(limit=limit)]
                self._json({"ok": True, "folders": folders})
                return

            match = re.fullmatch(r"/api/uploads/folders/(\d+)", path)
            if match:
                folder = get_folder(int(match.group(1)))
                if not folder:
                    self._json({"ok": False, "error": "folder not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._json({
                    "ok": True,
                    **_folder_detail(
                        folder,
                        uploaded_from=_first(params, "uploaded_from") or None,
                        uploaded_to=_first(params, "uploaded_to") or None,
                    ),
                })
                return

            self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_uploads_post(self, path: str) -> None:
        try:
            if path == "/api/uploads/folders":
                data = self._read_json_body()
                display_name = str(data.get("display_name") or "").strip()
                note = str(data.get("note") or "").strip()
                if not display_name:
                    self._json({"ok": False, "error": "display_name is required"}, HTTPStatus.BAD_REQUEST)
                    return
                folder = create_folder(display_name, note, source="upload")
                self._json({"ok": True, "folder": folder})
                return

            match = re.fullmatch(r"/api/uploads/folders/(\d+)/retry", path)
            if match:
                folder = get_folder(int(match.group(1)))
                if not folder:
                    self._json({"ok": False, "error": "folder not found"}, HTTPStatus.NOT_FOUND)
                    return
                folder = _folder_with_runtime_status(folder)
                recovery = folder.get("recovery") if isinstance(folder.get("recovery"), dict) else {}
                if folder.get("archived_at"):
                    self._json({"ok": False, "error": "archived folder cannot be retried"}, HTTPStatus.CONFLICT)
                    return
                if int(folder.get("image_count") or 0) <= 0:
                    self._json({"ok": False, "error": "資料夾沒有可重新處理的圖片"}, HTTPStatus.BAD_REQUEST)
                    return
                if folder.get("status") == "running" and not recovery.get("stale"):
                    self._json({"ok": False, "error": "資料夾仍在正常處理中，請等待或重新整理。"}, HTTPStatus.CONFLICT)
                    return
                pipeline = self._start_upload_pipeline(folder, trigger_source="upload")
                refreshed = get_folder(int(folder["id"])) or folder
                self._json({"ok": bool(pipeline.get("ok")), "folder": _folder_summary(refreshed), "pipeline": pipeline})
                return

            match = re.fullmatch(r"/api/uploads/folders/(\d+)/mark-failed", path)
            if match:
                folder = get_folder(int(match.group(1)))
                if not folder:
                    self._json({"ok": False, "error": "folder not found"}, HTTPStatus.NOT_FOUND)
                    return
                folder = _folder_with_runtime_status(folder)
                recovery = folder.get("recovery") if isinstance(folder.get("recovery"), dict) else {}
                if folder.get("status") == "success":
                    self._json({"ok": False, "error": "completed folder cannot be marked failed"}, HTTPStatus.CONFLICT)
                    return
                if folder.get("status") == "running" and not recovery.get("stale"):
                    self._json({"ok": False, "error": "資料夾仍在正常處理中，請等待或重新整理。"}, HTTPStatus.CONFLICT)
                    return
                stuck_step = str(recovery.get("stuck_step") or folder.get("current_step") or "ocr")
                steps = dict(folder.get("step_statuses") or {})
                if stuck_step in {"ocr", "compose", "index"}:
                    steps[stuck_step] = "failed"
                failed = update_folder_status(
                    int(folder["id"]),
                    status="failed",
                    current_step="failed",
                    step_statuses=steps,
                )
                self._json({"ok": bool(failed), "folder": _folder_summary(failed) if failed else None})
                return

            match = re.fullmatch(r"/api/uploads/folders/(\d+)/images", path)
            if match:
                folder = get_folder(int(match.group(1)))
                if not folder:
                    self._json({"ok": False, "error": "folder not found"}, HTTPStatus.NOT_FOUND)
                    return
                content_type = self.headers.get("Content-Type", "")
                length = int(self.headers.get("Content-Length", "0"))
                if length > MAX_UPLOAD_TOTAL_BYTES:
                    self._json({"ok": False, "error": "upload payload too large"}, HTTPStatus.BAD_REQUEST)
                    return
                body = self.rfile.read(length)
                fields, files = _parse_multipart_form(content_type, body)
                if not files:
                    self._json({"ok": False, "error": "no files uploaded"}, HTTPStatus.BAD_REQUEST)
                    return
                if len(files) > MAX_UPLOAD_FILE_COUNT:
                    self._json({"ok": False, "error": f"too many files; maximum is {MAX_UPLOAD_FILE_COUNT}"}, HTTPStatus.BAD_REQUEST)
                    return
                target_inbox = folder_target_path(folder) / "inbox"
                target_inbox.mkdir(parents=True, exist_ok=True)
                added = []
                rejected = []
                next_index = int(folder.get("image_count") or 0) + 1
                for file_item in files:
                    filename = str(file_item["filename"])
                    content = bytes(file_item["content"])
                    suffix = Path(filename).suffix.lower()
                    if suffix not in SUPPORTED_UPLOAD_EXT:
                        rejected.append(f"{filename}: unsupported format")
                        continue
                    if len(content) > MAX_UPLOAD_FILE_BYTES:
                        rejected.append(f"{filename}: file too large")
                        continue
                    size_error = _validate_upload_image_dimensions(content)
                    if size_error:
                        rejected.append(f"{filename}: {size_error}")
                        continue
                    while True:
                        target = target_inbox / safe_stored_filename(filename, next_index)
                        if not target.exists() and not stored_path_is_registered(target):
                            break
                        next_index += 1
                    target.write_bytes(content)
                    added.append(add_image(int(folder["id"]), target, filename))
                    next_index += 1
                if not added:
                    detail = "; ".join(rejected) if rejected else "no supported image files uploaded"
                    self._json({"ok": False, "error": detail}, HTTPStatus.BAD_REQUEST)
                    return
                folder = get_folder(int(folder["id"])) or folder
                pipeline = self._start_upload_pipeline(folder, trigger_source="upload")
                self._json({
                    "ok": bool(pipeline.get("ok")),
                    "folder": folder,
                    "images": added,
                    "rejected": rejected,
                    "pipeline": pipeline,
                })
                return

            match = re.fullmatch(r"/api/uploads/folders/(\d+)/download", path)
            if match:
                folder = get_folder(int(match.group(1)))
                if not folder:
                    self._json({"ok": False, "error": "folder not found"}, HTTPStatus.NOT_FOUND)
                    return
                data = self._read_json_body()
                files, skipped = _folder_download_files(
                    folder,
                    image_ids=list(data.get("image_ids") or []),
                    uploaded_from=str(data.get("uploaded_from") or "") or None,
                    uploaded_to=str(data.get("uploaded_to") or "") or None,
                )
                if not files:
                    self._json({
                        "ok": False,
                        "error": "沒有可下載的組圖結果",
                        "skipped": skipped,
                    }, HTTPStatus.BAD_REQUEST)
                    return
                self._send_download_zip(files)
                return

            match = re.fullmatch(r"/api/uploads/images/(\d+)/manual-tags", path)
            if match:
                data = self._read_json_body()
                tag = add_manual_tag(
                    int(match.group(1)),
                    str(data.get("tag") or ""),
                    note=str(data.get("note") or ""),
                    created_by=str(data.get("created_by") or "web"),
                )
                _refresh_upload_search_index_for_same_sha_images(int(match.group(1)))
                self._json({"ok": True, "tag": tag})
                return

            self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_uploads_delete(self, path: str) -> None:
        try:
            match = re.fullmatch(r"/api/uploads/folders/(\d+)", path)
            if match:
                folder = get_folder(int(match.group(1)))
                if not folder:
                    self._json({"ok": False, "error": "folder not found"}, HTTPStatus.NOT_FOUND)
                    return
                ok_to_archive, reason = _folder_can_be_archived(_folder_with_runtime_status(folder))
                if not ok_to_archive:
                    self._json({"ok": False, "error": reason}, HTTPStatus.CONFLICT)
                    return
                archived = archive_folder(int(match.group(1)), updated_by="web")
                self._json({"ok": bool(archived), "archived": bool(archived), "folder": archived})
                return

            match = re.fullmatch(r"/api/uploads/images/(\d+)", path)
            if match:
                image_id = int(match.group(1))
                record = _upload_image_record(image_id)
                if not record:
                    self._json({"ok": False, "error": "image not found"}, HTTPStatus.NOT_FOUND)
                    return
                image, folder = record
                if image.get("archived_at"):
                    self._json({"ok": False, "error": "image already archived"}, HTTPStatus.CONFLICT)
                    return
                ok_to_archive, reason = _image_can_be_archived(folder, image)
                if not ok_to_archive:
                    self._json({"ok": False, "error": reason}, HTTPStatus.CONFLICT)
                    return
                ok = archive_image(image_id, updated_by="web")
                if ok:
                    delete_image_search_index(image_id)
                self._json({"ok": ok, "archived": ok})
                return

            match = re.fullmatch(r"/api/uploads/manual-tags/(\d+)", path)
            if match:
                image_id = _image_id_for_manual_tag(int(match.group(1)))
                ok = delete_manual_tag(int(match.group(1)))
                if ok and image_id is not None:
                    _refresh_upload_search_index_for_same_sha_images(image_id)
                self._json({"ok": ok})
                return
            self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_uploads_patch(self, path: str) -> None:
        try:
            match = re.fullmatch(r"/api/uploads/images/(\d+)", path)
            if match:
                data = self._read_json_body()
                tags_value = data.get("ocr_tags_override")
                tags = tags_value if isinstance(tags_value, list) else None
                image = update_image_metadata(
                    int(match.group(1)),
                    display_name=str(data.get("display_name")) if "display_name" in data else None,
                    ocr_tags_override=tags,
                    reference_text=str(data.get("reference_text")) if "reference_text" in data else None,
                    manual_note=str(data.get("manual_note")) if "manual_note" in data else None,
                    updated_by=str(data.get("updated_by") or "web"),
                )
                if not image:
                    self._json({"ok": False, "error": "image not found"}, HTTPStatus.NOT_FOUND)
                    return
                _refresh_upload_search_index_for_same_sha_images(int(match.group(1)))
                self._json({"ok": True, "image": image})
                return

            match = re.fullmatch(r"/api/uploads/manual-tags/(\d+)", path)
            if match:
                data = self._read_json_body()
                tag = update_manual_tag(
                    int(match.group(1)),
                    str(data.get("tag") or ""),
                    note=str(data.get("note")) if "note" in data else None,
                )
                if not tag:
                    self._json({"ok": False, "error": "tag not found"}, HTTPStatus.NOT_FOUND)
                    return
                _refresh_upload_search_index_for_same_sha_images(int(tag["image_id"]))
                self._json({"ok": True, "tag": tag})
                return

            self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_chat(self) -> None:
        started = time.perf_counter()
        message = ""
        status = HTTPStatus.OK
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw)
            message = str(data.get("message") or "").strip()
            # Default raised from 12 to 100: with limit=12 + indexed_at-DESC
            # ordering, popular country queries (e.g. "日本", "韓國") routinely
            # truncated 20+ legitimate matches and dropped older travel DM
            # off the page. 100 is comfortable for the 1-2 group sizes we
            # see today; the chat UI can still pass an explicit smaller value.
            limit = int(data.get("limit") or 100)
            include_archived = bool(data.get("include_archived"))
            if not message:
                payload = {"kind": "empty", "message": "請輸入要交給 Agent 的旅遊任務。"}
            else:
                payload = _chat_payload(message, limit, include_archived=include_archived)
        except Exception as exc:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            payload = {"error": str(exc), "type": exc.__class__.__name__}

        duration_ms = int((time.perf_counter() - started) * 1000)
        count = int(payload.get("count") or 0) if isinstance(payload, dict) else 0
        if isinstance(payload, dict):
            payload = {
                **payload,
                "debug": {
                    "duration_ms": duration_ms,
                    "query": message,
                    "result_count": count,
                    "server_pid": os.getpid(),
                },
            }
        sys.stderr.write(f"chat query={message!r} status={int(status)} duration_ms={duration_ms} count={count}\n")
        try:
            CHAT_REQUEST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with CHAT_REQUEST_LOG_PATH.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps({
                    "at": datetime.now(timezone.utc).isoformat(),
                    "query": message,
                    "status": int(status),
                    "duration_ms": duration_ms,
                    "count": count,
                    "pid": os.getpid(),
                    "user_agent": self.headers.get("User-Agent", ""),
                    "forwarded_for": self.headers.get("X-Forwarded-For", ""),
                    "forwarded_proto": self.headers.get("X-Forwarded-Proto", ""),
                }, ensure_ascii=False) + "\n")
        except Exception as log_exc:
            sys.stderr.write(f"chat request log failed: {log_exc}\n")

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        encoded_query = base64.urlsafe_b64encode(message.encode("utf-8")).decode("ascii").rstrip("=")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-OpenClaw-Duration-Ms", str(duration_ms))
        self.send_header("X-OpenClaw-Result-Count", str(count))
        self.send_header("X-OpenClaw-Server-Pid", str(os.getpid()))
        self.send_header("X-OpenClaw-Query-Encoding", "utf-8-base64url")
        self.send_header("X-OpenClaw-Query", encoded_query)
        self.end_headers()
        self.wfile.write(body)

    def _handle_clipboard(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw)
            media_ids = data.get("media_ids") or []
            if isinstance(media_ids, str):
                media_ids = [media_ids]
            files = _media_ids_to_files(list(media_ids))
            self._json(_copy_files_to_windows_clipboard(files))
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _send_download_zip(self, files: list[Path]) -> None:
        if not files:
            self._json({"ok": False, "error": "no files"}, HTTPStatus.BAD_REQUEST)
            return

        body = _zip_bytes_for_files(files)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="agent-dm-images.zip"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_download(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw)
            media_ids = data.get("media_ids") or []
            if isinstance(media_ids, str):
                media_ids = [media_ids]
            files = _media_ids_to_files(list(media_ids))
            self._send_download_zip(files)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_duplicate_review(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw)
            action = str(data.get("action") or "keep_one")
            group_id = str(data.get("group_id") or "").strip()
            keep = data.get("keep_sidecar_paths") or []
            archive = data.get("archived_sidecar_paths") or []
            if isinstance(keep, str):
                keep = [keep]
            if isinstance(archive, str):
                archive = [archive]
            if not group_id:
                self._json({"ok": False, "error": "group_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            if action == "keep_one" and not keep:
                self._json({"ok": False, "error": "keep_sidecar_paths is required"}, HTTPStatus.BAD_REQUEST)
                return
            result = record_duplicate_review(
                group_id,
                list(keep),
                action=action,
                archived_sidecar_paths=list(archive),
                reviewer=str(data.get("reviewer") or "web"),
                note=str(data.get("note") or "") or None,
            )
            self._json(result)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_run(self) -> None:
        try:
            if not _read_openclaw_settings().get("line_auto_enabled", True):
                self._json({
                    "ok": False,
                    "kind": "manual-run",
                    "started": False,
                    "error": "LINE 自動抓圖目前已停用，請改用圖片上傳流程。",
                }, HTTPStatus.CONFLICT)
                return
            if not RUN_RPA_SCRIPT.is_file():
                self._json({"ok": False, "error": "manual run script missing"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            claimed, job = _try_claim_manual_run()
            if not claimed:
                self._json({
                    "ok": True,
                    "kind": "manual-run",
                    "started": False,
                    "job": job,
                    "latest_job": _latest_job_snapshot(),
                    "message": "Agent 流程仍在執行中。",
                })
                return
            try:
                process = subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(RUN_RPA_SCRIPT),
                        "-TriggerSource",
                        "manual",
                    ],
                    cwd=str(PROJECT_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            except Exception as exc:
                _abandon_manual_run(f"failed to spawn manual run: {exc}")
                raise
            job = _set_manual_job(pid=process.pid)
            threading.Thread(target=_watch_manual_process, args=(process,), daemon=True).start()
            self._json({
                "ok": True,
                "kind": "manual-run",
                "started": True,
                "pid": process.pid,
                "job": job,
                "latest_job": _latest_job_snapshot(),
                "message": "已手動觸發抓取+OCR+組圖，完成前前端會顯示 LINE圖片處理中。",
            })
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_media(self, params: dict[str, list[str]], *, thumbnail: bool = False) -> None:
        media_id = _first(params, "id")
        raw = _first(params, "path")
        if media_id:
            raw = _db_image_path(media_id)
        if not raw:
            self.send_error(HTTPStatus.BAD_REQUEST, "missing path")
            return

        candidate = _resolve_project_file(raw)
        if candidate is None:
            self.send_error(HTTPStatus.FORBIDDEN, "path outside project")
            return

        thumbnail_failed = False
        if thumbnail:
            try:
                candidate = _ensure_thumbnail(candidate, _as_int(_first(params, "w", "360"), 360) or 360)
            except Exception as exc:
                # Don't send the original full-size image with an immutable
                # year-long cache header — a single transient failure would
                # otherwise pin a 5-15 MB original in every downstream cache
                # under the thumbnail URL.
                sys.stderr.write(f"[openclaw_web] thumbnail failed for {candidate}: {exc}\n")
                thumbnail_failed = True

        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(candidate.stat().st_size))
        if thumbnail_failed:
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        with candidate.open("rb") as fh:
            shutil.copyfileobj(fh, self.wfile, 64 * 1024)


def _configure_logging() -> None:
    """Send logs to console + logs/openclaw/web.log so server-side failures are
    no longer invisible. Safe to call once at startup."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_path = PROJECT_ROOT / "logs" / "openclaw" / "web.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
    )


def main() -> int:
    _configure_logging()
    port = _as_int(sys.argv[1] if len(sys.argv) > 1 else "4173", 4173) or 4173
    if AUTH_USERNAME == DEFAULT_AUTH_USERNAME and AUTH_PASSWORD == DEFAULT_AUTH_PASSWORD:
        logger.warning(
            "using built-in default credentials; set OPENCLAW_WEB_USER and "
            "OPENCLAW_WEB_PASSWORD before exposing this service publicly"
        )
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("Agent travel interface listening on http://0.0.0.0:%s/", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
