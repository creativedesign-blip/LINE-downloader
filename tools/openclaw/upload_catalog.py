from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from tools.common.image_seen import file_sha256
from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT, relpath_from_root


CATALOG_DB_PATH = PROJECT_ROOT / "logs" / "openclaw" / "upload_catalog.db"
INVALID_LINE_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify_folder_name(value: str, *, fallback: str = "upload") -> str:
    raw = re.sub(r"\s+", "_", value.strip())
    raw = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", raw)
    raw = raw.strip("._-")
    return raw[:80] or fallback


def line_group_folder_name(value: str) -> str:
    sanitized = INVALID_LINE_PATH_CHARS.sub("_", value).strip().rstrip(".")
    return sanitized or "unnamed_group"


def line_folder_slug(group_names: list[str], timestamp: str | None = None) -> str:
    names = [slugify_folder_name(name, fallback="group") for name in group_names if name.strip()]
    label = "_".join(names[:2]) or "line"
    if len(names) > 2:
        label = f"{label}_plus{len(names) - 2}"
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"line_auto_{stamp}_{label}"


def upload_folder_slug(display_name: str, timestamp: str | None = None) -> str:
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"upload_{stamp}_{slugify_folder_name(display_name)}"


def connect(db_path: Path = CATALOG_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS upload_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_slug TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'upload',
            status TEXT NOT NULL DEFAULT 'pending',
            current_step TEXT NOT NULL DEFAULT 'upload',
            step_statuses TEXT NOT NULL DEFAULT '{}',
            image_count INTEGER NOT NULL DEFAULT 0,
            line_groups TEXT NOT NULL DEFAULT '[]',
            captured_at TEXT,
            job_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS uploaded_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            original_filename TEXT NOT NULL,
            stored_path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            ocr_tags_override TEXT NOT NULL DEFAULT '[]',
            reference_text TEXT NOT NULL DEFAULT '',
            manual_note TEXT NOT NULL DEFAULT '',
            archived_at TEXT,
            updated_at TEXT,
            updated_by TEXT NOT NULL DEFAULT 'web',
            uploaded_at TEXT NOT NULL,
            ocr_status TEXT NOT NULL DEFAULT 'pending',
            compose_status TEXT NOT NULL DEFAULT 'pending',
            FOREIGN KEY(folder_id) REFERENCES upload_folders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS manual_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT 'web',
            created_at TEXT NOT NULL,
            FOREIGN KEY(image_id) REFERENCES uploaded_images(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_upload_folders_created
            ON upload_folders(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_uploaded_images_folder
            ON uploaded_images(folder_id);
        CREATE INDEX IF NOT EXISTS idx_manual_tags_image
            ON manual_tags(image_id);
        """
    )
    _ensure_columns(
        conn,
        "uploaded_images",
        {
            "display_name": "TEXT NOT NULL DEFAULT ''",
            "ocr_tags_override": "TEXT NOT NULL DEFAULT '[]'",
            "reference_text": "TEXT NOT NULL DEFAULT ''",
            "manual_note": "TEXT NOT NULL DEFAULT ''",
            "archived_at": "TEXT",
            "updated_at": "TEXT",
            "updated_by": "TEXT NOT NULL DEFAULT 'web'",
        },
    )
    conn.commit()


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _json_loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _folder_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "folder_slug": row["folder_slug"],
        "display_name": row["display_name"],
        "note": row["note"],
        "source": row["source"],
        "status": row["status"],
        "current_step": row["current_step"],
        "step_statuses": _json_loads(row["step_statuses"], {}),
        "image_count": row["image_count"],
        "line_groups": _json_loads(row["line_groups"], []),
        "captured_at": row["captured_at"],
        "job_id": row["job_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "target_id": row["folder_slug"],
    }


def _image_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "folder_id": row["folder_id"],
        "original_filename": row["original_filename"],
        "stored_path": row["stored_path"],
        "sha256": row["sha256"],
        "display_name": row["display_name"],
        "ocr_tags_override": _json_loads(row["ocr_tags_override"], []),
        "reference_text": row["reference_text"],
        "manual_note": row["manual_note"],
        "archived_at": row["archived_at"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
        "uploaded_at": row["uploaded_at"],
        "ocr_status": row["ocr_status"],
        "compose_status": row["compose_status"],
    }


def create_folder(
    display_name: str,
    note: str = "",
    *,
    source: str = "upload",
    folder_slug: str | None = None,
    line_groups: list[str] | None = None,
    captured_at: str | None = None,
    db_path: Path = CATALOG_DB_PATH,
) -> dict[str, Any]:
    now = utc_now_iso()
    if folder_slug is None:
        folder_slug = upload_folder_slug(display_name) if source == "upload" else line_folder_slug(line_groups or [], None)
    with closing(connect(db_path)) as conn:
        cursor = conn.execute(
            """
            INSERT INTO upload_folders (
                folder_slug, display_name, note, source, status, current_step,
                step_statuses, image_count, line_groups, captured_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', 'upload', '{}', 0, ?, ?, ?, ?)
            """,
            (
                folder_slug,
                display_name.strip() or folder_slug,
                note.strip(),
                source,
                json.dumps(line_groups or [], ensure_ascii=False),
                captured_at,
                now,
                now,
            ),
        )
        folder_id = int(cursor.lastrowid)
        conn.commit()
        return get_folder(folder_id, db_path=db_path) or {}


def read_line_groups_from_config(config_path: Path) -> list[str]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    excel_path = Path(str(config.get("excel_path") or "line.XLSX"))
    if not excel_path.is_absolute():
        excel_path = (config_path.parent / excel_path).resolve()
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active
    groups: list[str] = []
    for row in ws.iter_rows(min_col=1, max_col=1, values_only=True):
        value = row[0]
        if value is None:
            continue
        text = str(value).strip()
        if text:
            groups.append(text)
    wb.close()
    return groups


def prepare_line_run_folder(
    config_path: Path,
    *,
    timestamp: str | None = None,
    db_path: Path = CATALOG_DB_PATH,
) -> dict[str, Any]:
    groups = read_line_groups_from_config(config_path)
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    display_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    slug = line_folder_slug(groups, stamp)
    display_name = f"LINE 自動爬取 {display_time}"
    note = "已爬取群組：" + ("、".join(groups) if groups else "未偵測到群組")
    return create_folder(
        display_name,
        note,
        source="line-auto",
        folder_slug=slug,
        line_groups=groups,
        captured_at=utc_now_iso(),
        db_path=db_path,
    )


def get_folder(folder_id: int, *, db_path: Path = CATALOG_DB_PATH) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM upload_folders WHERE id = ?", (folder_id,)).fetchone()
    return _folder_from_row(row) if row else None


def get_folder_by_slug(folder_slug: str, *, db_path: Path = CATALOG_DB_PATH) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM upload_folders WHERE folder_slug = ?", (folder_slug,)).fetchone()
    return _folder_from_row(row) if row else None


def list_folders(*, limit: int = 50, db_path: Path = CATALOG_DB_PATH) -> list[dict[str, Any]]:
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM upload_folders ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
    return [_folder_from_row(row) for row in rows]


def update_folder_status(
    folder_id: int,
    *,
    status: str | None = None,
    current_step: str | None = None,
    step_statuses: dict[str, Any] | None = None,
    job_id: str | None = None,
    db_path: Path = CATALOG_DB_PATH,
) -> dict[str, Any] | None:
    folder = get_folder(folder_id, db_path=db_path)
    if not folder:
        return None
    merged_steps = dict(folder.get("step_statuses") or {})
    if step_statuses:
        merged_steps.update(step_statuses)
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            UPDATE upload_folders
            SET status = ?, current_step = ?, step_statuses = ?, job_id = COALESCE(?, job_id), updated_at = ?
            WHERE id = ?
            """,
            (
                status or folder["status"],
                current_step or folder["current_step"],
                json.dumps(merged_steps, ensure_ascii=False),
                job_id,
                utc_now_iso(),
                folder_id,
            ),
        )
        conn.commit()
    return get_folder(folder_id, db_path=db_path)


def add_image(
    folder_id: int,
    source_path: Path,
    original_filename: str,
    *,
    db_path: Path = CATALOG_DB_PATH,
) -> dict[str, Any]:
    digest = file_sha256(source_path)
    rel = relpath_from_root(source_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        cursor = conn.execute(
            """
            INSERT INTO uploaded_images (
                folder_id, original_filename, stored_path, sha256, uploaded_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (folder_id, original_filename, rel, digest, now),
        )
        conn.execute(
            """
            UPDATE upload_folders
            SET image_count = image_count + 1, updated_at = ?
            WHERE id = ?
            """,
            (now, folder_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM uploaded_images WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _image_from_row(row)


def safe_stored_filename(original_filename: str, index: int) -> str:
    source = Path(original_filename)
    stem = slugify_folder_name(source.stem, fallback="image")
    suffix = source.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        suffix = ".jpg"
    return f"{index:04d}_{stem}{suffix}"


def stored_path_is_registered(path: Path, *, db_path: Path = CATALOG_DB_PATH) -> bool:
    rel = relpath_from_root(path)
    with closing(connect(db_path)) as conn:
        row = conn.execute("SELECT 1 FROM uploaded_images WHERE stored_path = ? LIMIT 1", (rel,)).fetchone()
    return row is not None


def ingest_line_run_images(
    folder_id: int,
    config_path: Path,
    *,
    started_at_epoch: float,
    db_path: Path = CATALOG_DB_PATH,
) -> list[dict[str, Any]]:
    folder = get_folder(folder_id, db_path=db_path)
    if not folder:
        raise ValueError(f"folder not found: {folder_id}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    save_root = Path(str(config.get("save_root") or "download"))
    if not save_root.is_absolute():
        save_root = (config_path.parent / save_root).resolve()
    groups = folder.get("line_groups") or read_line_groups_from_config(config_path)
    target_inbox = folder_target_path(folder) / "inbox"
    target_inbox.mkdir(parents=True, exist_ok=True)
    added: list[dict[str, Any]] = []
    supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
    seen_hashes: set[str] = set()
    index = 1
    for group in groups:
        group_dir = save_root / line_group_folder_name(str(group))
        if not group_dir.exists():
            continue
        for image_path in sorted(group_dir.iterdir(), key=lambda p: p.stat().st_mtime if p.is_file() else 0):
            if not image_path.is_file() or image_path.suffix.lower() not in supported:
                continue
            try:
                if image_path.stat().st_mtime < started_at_epoch:
                    continue
                digest = file_sha256(image_path)
            except OSError:
                continue
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            group_prefix = slugify_folder_name(str(group), fallback="group")
            while True:
                filename = f"{group_prefix}_{safe_stored_filename(image_path.name, index)}"
                target = target_inbox / filename
                if not target.exists() and not stored_path_is_registered(target, db_path=db_path):
                    break
                index += 1
            shutil.copy2(image_path, target)
            added.append(add_image(folder_id, target, image_path.name, db_path=db_path))
            index += 1
    if added:
        update_folder_status(
            folder_id,
            status="running",
            current_step="ocr",
            step_statuses={"upload": "success"},
            db_path=db_path,
        )
    return added


def list_images(folder_id: int, *, db_path: Path = CATALOG_DB_PATH) -> list[dict[str, Any]]:
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM uploaded_images WHERE folder_id = ? AND archived_at IS NULL ORDER BY uploaded_at, id",
            (folder_id,),
        ).fetchall()
    return [_image_from_row(row) for row in rows]


def update_image_metadata(
    image_id: int,
    *,
    display_name: str | None = None,
    ocr_tags_override: list[str] | None = None,
    reference_text: str | None = None,
    manual_note: str | None = None,
    updated_by: str = "web",
    db_path: Path = CATALOG_DB_PATH,
) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM uploaded_images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            return None
        current = _image_from_row(row)
        tags = current["ocr_tags_override"] if ocr_tags_override is None else [
            str(tag).strip()
            for tag in ocr_tags_override
            if str(tag).strip()
        ]
        conn.execute(
            """
            UPDATE uploaded_images
            SET display_name = ?, ocr_tags_override = ?, reference_text = ?,
                manual_note = ?, updated_at = ?, updated_by = ?
            WHERE id = ?
            """,
            (
                (display_name if display_name is not None else current["display_name"]).strip(),
                json.dumps(tags, ensure_ascii=False),
                (reference_text if reference_text is not None else current["reference_text"]).strip(),
                (manual_note if manual_note is not None else current["manual_note"]).strip(),
                utc_now_iso(),
                updated_by.strip() or "web",
                image_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM uploaded_images WHERE id = ?", (image_id,)).fetchone()
    return _image_from_row(row) if row else None


def archive_image(image_id: int, *, updated_by: str = "web", db_path: Path = CATALOG_DB_PATH) -> bool:
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        row = conn.execute("SELECT folder_id FROM uploaded_images WHERE id = ? AND archived_at IS NULL", (image_id,)).fetchone()
        if not row:
            return False
        conn.execute(
            """
            UPDATE uploaded_images
            SET archived_at = ?, updated_at = ?, updated_by = ?
            WHERE id = ?
            """,
            (now, now, updated_by.strip() or "web", image_id),
        )
        conn.execute(
            """
            UPDATE upload_folders
            SET image_count = CASE WHEN image_count > 0 THEN image_count - 1 ELSE 0 END,
                updated_at = ?
            WHERE id = ?
            """,
            (now, int(row["folder_id"])),
        )
        conn.commit()
    return True


def list_manual_tags(image_id: int, *, db_path: Path = CATALOG_DB_PATH) -> list[dict[str, Any]]:
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM manual_tags WHERE image_id = ? ORDER BY created_at, id",
            (image_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_manual_tag(
    image_id: int,
    tag: str,
    *,
    note: str = "",
    created_by: str = "web",
    db_path: Path = CATALOG_DB_PATH,
) -> dict[str, Any]:
    tag = tag.strip()
    if not tag:
        raise ValueError("tag is required")
    with closing(connect(db_path)) as conn:
        cursor = conn.execute(
            """
            INSERT INTO manual_tags (image_id, tag, note, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (image_id, tag, note.strip(), created_by, utc_now_iso()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM manual_tags WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def delete_manual_tag(tag_id: int, *, db_path: Path = CATALOG_DB_PATH) -> bool:
    with closing(connect(db_path)) as conn:
        cursor = conn.execute("DELETE FROM manual_tags WHERE id = ?", (tag_id,))
        conn.commit()
        return cursor.rowcount > 0


def update_manual_tag(
    tag_id: int,
    tag: str,
    *,
    note: str | None = None,
    db_path: Path = CATALOG_DB_PATH,
) -> dict[str, Any] | None:
    tag = tag.strip()
    if not tag:
        raise ValueError("tag is required")
    with closing(connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM manual_tags WHERE id = ?", (tag_id,)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE manual_tags SET tag = ?, note = ? WHERE id = ?",
            (tag, (note if note is not None else row["note"]).strip(), tag_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM manual_tags WHERE id = ?", (tag_id,)).fetchone()
    return dict(row) if row else None


def folder_target_path(folder: dict[str, Any]) -> Path:
    return DOWNLOADS_DIR / str(folder["folder_slug"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    update = sub.add_parser("update-folder")
    update.add_argument("--id", type=int, required=True)
    update.add_argument("--status")
    update.add_argument("--current-step")
    update.add_argument("--job-id")
    update.add_argument("--step", action="append", default=[], help="name=status")

    prepare_line = sub.add_parser("prepare-line-run")
    prepare_line.add_argument("--config", type=Path, required=True)
    prepare_line.add_argument("--timestamp")

    ingest_line = sub.add_parser("ingest-line-run")
    ingest_line.add_argument("--id", type=int, required=True)
    ingest_line.add_argument("--config", type=Path, required=True)
    ingest_line.add_argument("--started-at-epoch", type=float, required=True)

    args = parser.parse_args(argv)
    if args.command == "update-folder":
        steps: dict[str, str] = {}
        for item in args.step:
            name, _, status = item.partition("=")
            if name and status:
                steps[name] = status
        folder = update_folder_status(
            args.id,
            status=args.status,
            current_step=args.current_step,
            step_statuses=steps,
            job_id=args.job_id,
        )
        print(json.dumps(folder or {}, ensure_ascii=False))
        return 0 if folder else 1
    if args.command == "prepare-line-run":
        folder = prepare_line_run_folder(args.config, timestamp=args.timestamp)
        print(json.dumps(folder, ensure_ascii=False))
        return 0
    if args.command == "ingest-line-run":
        images = ingest_line_run_images(
            args.id,
            args.config,
            started_at_epoch=args.started_at_epoch,
        )
        print(json.dumps({"images": images, "count": len(images)}, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
