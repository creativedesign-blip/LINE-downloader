from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from pathlib import Path
from urllib import error, request

from tools.sync.config import SyncConfig
from tools.sync.models import AssetMedia, MediaResult


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class MediaUploadError(RuntimeError):
    pass


class MediaUploader:
    def __init__(self, config: SyncConfig):
        self.config = config

    def upload(self, media: AssetMedia) -> MediaResult:
        if media.file_path is None or not media.file_path.is_file():
            raise MediaUploadError(f"missing media file: {media.source_path}")
        sha = file_sha256(media.file_path)
        body, content_type = _multipart_body(
            file_path=media.file_path,
            fields={
                "external_id": media.asset_id,
                "sha256": sha,
                "source_kind": media.source_kind,
                "source_path": media.source_path,
            },
        )
        req = request.Request(
            self.config.media_upload_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.media_bearer_token}",
                "Content-Type": content_type,
            },
        )
        try:
            with request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MediaUploadError(f"media upload HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # pragma: no cover - exact network exceptions vary
            raise MediaUploadError(f"media upload failed: {exc}") from exc
        if int(payload.get("code", 0)) != 200:
            raise MediaUploadError(str(payload))
        data = payload.get("data") or {}
        if data.get("sha256") and str(data["sha256"]).lower() != sha:
            raise MediaUploadError("media upload sha256 mismatch")
        media_id = str(data.get("media_id") or "")
        url = str(data.get("url") or "")
        if not media_id or not url:
            raise MediaUploadError(f"media upload response missing media_id/url: {payload}")
        return MediaResult(
            media_id=media_id,
            url=url,
            sha256=sha,
            size=data.get("size"),
            deduplicated=bool(data.get("deduplicated")),
            raw=data,
        )


class FakeMediaUploader:
    def upload(self, media: AssetMedia) -> MediaResult:
        if media.file_path is None or not media.file_path.is_file():
            raise MediaUploadError(f"missing media file: {media.source_path}")
        sha = file_sha256(media.file_path)
        suffix = media.file_path.suffix.lower() or ".jpg"
        return MediaResult(
            media_id=f"{sha}{suffix}",
            url=f"https://crm.example.test/uploads/{sha}{suffix}",
            sha256=sha,
            size=media.file_path.stat().st_size,
            deduplicated=False,
            raw={"fake": True},
        )


def _multipart_body(*, file_path: Path, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----crm-sync-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{file_path.name}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {mime}\r\n\r\n".encode("ascii"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
