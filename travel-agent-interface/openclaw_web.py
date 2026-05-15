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
LATEST_JOB_PATH = PROJECT_ROOT / "logs" / "openclaw" / "latest_job.json"
RUN_LOCK_PATH = PROJECT_ROOT / "logs" / "openclaw" / "line-rpa-scheduled.lock"
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
    if latest and latest.get("trigger_source") == "manual":
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
        if parsed.path.startswith("/api/openclaw/") and not self._require_auth():
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

    def _handle_chat(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw)
            message = str(data.get("message") or "").strip()
            limit = int(data.get("limit") or 12)
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
                last_started_at=_utc_now_iso(),
                last_finished_at=None,
                last_success=None,
                last_error=None,
                returncode=None,
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
