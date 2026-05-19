from __future__ import annotations

import json
import base64
import hashlib
import hmac
import io
import mimetypes
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image, ImageOps


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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

JOB_LOCK = threading.Lock()
MANUAL_JOB: dict[str, object] = {
    "running": False,
    "pid": None,
    "last_started_at": None,
    "last_finished_at": None,
    "last_success": None,
    "last_error": None,
    "returncode": None,
}
AUTH_USERNAME = os.environ.get("OPENCLAW_WEB_USER", "admin_dadova")
AUTH_PASSWORD = os.environ.get("OPENCLAW_WEB_PASSWORD", "StarBit123")
AUTH_COOKIE_NAME = "openclaw_session"
AUTH_SESSION_TTL_SECONDS = 12 * 60 * 60

from tools.openclaw.operations import (  # noqa: E402
    DEFAULT_DB_PATH,
    check_duplicates,
    processing_status,
    query_itineraries,
    query_latest_results,
    record_duplicate_review,
)
from tools.openclaw.upload_catalog import (  # noqa: E402
    add_image,
    add_manual_tag,
    archive_image,
    create_folder,
    delete_manual_tag,
    folder_target_path,
    get_folder,
    list_folders,
    list_images,
    list_manual_tags,
    safe_stored_filename,
    stored_path_is_registered,
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


def _auth_secret() -> bytes:
    raw = os.environ.get("OPENCLAW_WEB_AUTH_SECRET")
    if raw:
        return raw.encode("utf-8")
    return hashlib.sha256(f"{AUTH_USERNAME}:{AUTH_PASSWORD}:{PROJECT_ROOT}".encode("utf-8")).digest()


def _sign_auth_session(username: str, expires_at: int) -> str:
    body = f"{username}|{expires_at}".encode("utf-8")
    return hmac.new(_auth_secret(), body, hashlib.sha256).hexdigest()


def _encode_auth_session(username: str) -> str:
    expires_at = int(time.time()) + AUTH_SESSION_TTL_SECONDS
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

    with sqlite3.connect(str(DEFAULT_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT sidecar_path, image_path, branded_path FROM itineraries "
            "WHERE sidecar_path = ? OR image_path = ? OR branded_path = ? LIMIT 1",
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
        raw = _db_image_path(str(value or ""))
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


def _with_media_urls(payload: dict) -> dict:
    def convert_item(item: dict) -> dict:
        copy = dict(item)
        image_key = copy.get("sidecar_path") or copy.get("branded_path") or copy.get("image_path")
        if image_key:
            media_id = _media_id(image_key)
            copy["media_id"] = media_id
            copy["image_url"] = f"/media?id={media_id}"
            copy["thumbnail_url"] = f"/media/thumbnail?id={media_id}&w=360"
            copy["preview_url"] = f"/media/thumbnail?id={media_id}&w=1200"
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
        part = part.strip()
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip()
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
        content = content.rstrip(b"\r\n")
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


def _system_tags_for_image(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    sidecar = path.with_suffix(path.suffix + ".json")
    if not sidecar.is_file():
        return []
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tags: list[dict[str, object]] = []
    for key in ("countries", "regions", "features", "months"):
        values = payload.get(key)
        if isinstance(values, list):
            tags.extend({"tag": str(value), "source": "ocr", "field": key} for value in values if value)
    duration = payload.get("duration_days")
    if duration:
        tags.append({"tag": f"{duration}天", "source": "ocr", "field": "duration_days"})
    return tags


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


def _branded_images_by_source(folder: dict[str, object]) -> dict[str, Path]:
    branded_dir = folder_target_path(folder) / "branded"
    if not branded_dir.is_dir():
        return {}

    by_source: dict[str, Path] = {}
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
    return by_source


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
    return copy


def _folder_detail(folder: dict[str, object]) -> dict[str, object]:
    folder = _folder_with_runtime_status(folder)
    folder = {**folder, **_folder_pipeline_counts(folder)}
    branded_by_source = _branded_images_by_source(folder)
    images = []
    for image in list_images(int(folder["id"])):
        current_path = _find_current_image_path(image, folder)
        image_copy = dict(image)
        if current_path is not None:
            rel = current_path.relative_to(PROJECT_ROOT).as_posix()
            image_copy["current_path"] = rel
            image_copy["media_id"] = _media_id(rel)
            image_copy["image_url"] = f"/media?path={rel}"
            image_copy["thumbnail_url"] = f"/media/thumbnail?path={rel}&w=360"
            branded = branded_by_source.get(rel)
            if branded is not None:
                branded_rel = branded.relative_to(PROJECT_ROOT).as_posix()
                image_copy["branded_path"] = branded_rel
                image_copy["branded_url"] = f"/media?path={branded_rel}"
                image_copy["branded_thumbnail_url"] = f"/media/thumbnail?path={branded_rel}&w=360"
        image_copy["manual_tags"] = list_manual_tags(int(image["id"]))
        image_copy["system_tags"] = _system_tags_for_image(current_path)
        images.append(image_copy)
    return {"folder": folder, "images": images}


def _folder_summary(folder: dict[str, object]) -> dict[str, object]:
    folder = _folder_with_runtime_status(folder)
    return {**folder, **_folder_pipeline_counts(folder)}


def _chat_payload(message: str, limit: int, *, include_archived: bool = False) -> dict:
    lower = message.lower()
    if any(token in message for token in ["狀態", "進度", "處理狀況", "資料庫", "db"]) or "status" in lower:
        payload = _status_with_manual_job()
        payload["kind"] = "status"
        payload["message"] = "Agent 狀態已讀取。"
        return payload

    if any(token in message for token in ["重複", "相同", "去重"]) or "duplicate" in lower:
        payload = _with_media_urls(check_duplicates(limit_groups=min(limit, 30), include_same_source=True))
        payload["kind"] = "duplicates"
        payload["message"] = f"Agent 找到 {payload.get('count', 0)} 組可能重複圖片。"
        return payload

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
        payload = _with_media_urls(payload)
        payload["kind"] = "latest"
        payload["message"] = (
            f"Agent 找到 {payload.get('count', 0)} 份今日組圖 DM。"
            if is_today and is_combo
            else f"Agent 找到 {payload.get('count', 0)} 份最新旅遊 DM。"
        )
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


class Handler(SimpleHTTPRequestHandler):
    server_version = "AgentTravelInterface/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self) -> None:
        # Clipboard image writes are controlled by browser security policy.
        # The user must still grant/trigger permission, but this header makes
        # the app's intent explicit through reverse proxies and browser checks.
        self.send_header("Permissions-Policy", "clipboard-write=(self), clipboard-read=(self)")
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

            token = _encode_auth_session(username)
            cookie = self._auth_cookie_header(token, max_age=AUTH_SESSION_TTL_SECONDS)
            self._json_auth_response(
                {"ok": True, "authenticated": True, "username": username},
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
        if parsed.path.startswith("/api/openclaw/") and not self._require_auth():
            return
        if parsed.path == "/api/openclaw/settings":
            self._handle_settings_update()
            return
        if parsed.path == "/api/openclaw/chat":
            self._handle_chat()
            return
        if parsed.path == "/api/openclaw/clipboard":
            self._handle_clipboard()
            return
        if parsed.path == "/api/openclaw/download":
            self._handle_download()
            return
        if parsed.path == "/api/openclaw/duplicates/review":
            self._handle_duplicate_review()
            return
        if parsed.path == "/api/openclaw/run":
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
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_api(self, path: str, params: dict[str, list[str]]) -> None:
        try:
            if path == "/api/openclaw/status":
                self._json(_status_with_manual_job(target_id=_first(params, "target") or None))
                return

            if path == "/api/openclaw/settings":
                self._json({"ok": True, "settings": _read_openclaw_settings()})
                return

            if path == "/api/openclaw/run":
                self._json({"kind": "manual-run", "job": _manual_job_snapshot(), "latest_job": _latest_job_snapshot()})
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
                self._json(_with_media_urls(payload))
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

    def _start_upload_pipeline(self, folder: dict[str, object], *, trigger_source: str = "upload") -> dict[str, object]:
        latest = _latest_job_snapshot()
        current = _manual_job_snapshot()
        if current.get("running") or _is_recent_run_lock() or (latest and latest.get("status") == "running"):
            return {
                "ok": True,
                "started": False,
                "job": latest or current,
                "message": "目前已有圖片流程執行中",
            }
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
        return {"ok": True, "started": True, "pid": process.pid}

    def _handle_uploads_get(self, path: str, params: dict[str, list[str]]) -> None:
        try:
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
                self._json({"ok": True, **_folder_detail(folder)})
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
                self._json({"ok": bool(pipeline.get("ok")), "folder": folder, "images": added, "pipeline": pipeline})
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
                self._json({"ok": True, "tag": tag})
                return

            if path == "/api/openclaw/settings":
                data = self._read_json_body()
                settings = {}
                if "line_auto_enabled" in data:
                    settings["line_auto_enabled"] = bool(data.get("line_auto_enabled"))
                self._json({"ok": True, "settings": _write_openclaw_settings(settings)})
                return

            self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_uploads_delete(self, path: str) -> None:
        try:
            match = re.fullmatch(r"/api/uploads/images/(\d+)", path)
            if match:
                ok = archive_image(int(match.group(1)), updated_by="web")
                self._json({"ok": ok, "archived": ok})
                return

            match = re.fullmatch(r"/api/uploads/manual-tags/(\d+)", path)
            if match:
                ok = delete_manual_tag(int(match.group(1)))
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
                self._json({"ok": True, "tag": tag})
                return

            self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_chat(self) -> None:
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
                self._json({"kind": "empty", "message": "請輸入要交給 Agent 的旅遊任務。"})
                return
            self._json(_chat_payload(message, limit, include_archived=include_archived))
        except Exception as exc:
            self._json({"error": str(exc), "type": exc.__class__.__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

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
            current = _manual_job_snapshot()
            latest = _latest_job_snapshot()
            if current.get("running") or _is_recent_run_lock() or (latest and latest.get("status") == "running"):
                job = current
                if latest and latest.get("status") == "running":
                    job = _job_compat_from_latest(latest) or current
                self._json({
                    "ok": True,
                    "kind": "manual-run",
                    "started": False,
                    "job": job,
                    "latest_job": latest,
                    "message": "Agent 流程仍在執行中。",
                })
                return
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
            job = _set_manual_job(
                running=True,
                pid=process.pid,
                status="running",
                job_id=None,
                trigger_source="manual",
                last_started_at=_utc_now_iso(),
                last_finished_at=None,
                last_success=None,
                last_error=None,
                returncode=None,
                steps={},
                log_path=None,
            )
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

        if thumbnail:
            try:
                candidate = _ensure_thumbnail(candidate, _as_int(_first(params, "w", "360"), 360) or 360)
            except Exception:
                pass

        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        with candidate.open("rb") as fh:
            self.wfile.write(fh.read())


def main() -> int:
    port = _as_int(sys.argv[1] if len(sys.argv) > 1 else "4173", 4173) or 4173
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Agent travel interface listening on http://0.0.0.0:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
