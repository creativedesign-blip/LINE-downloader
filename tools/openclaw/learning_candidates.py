"""Manual-upload learning candidates for improving LINE auto grouping.

Manual uploads are trusted as travel images. When the first-pass OCR rule
would have classified one as review/other, this module records a small
candidate rule that the user can later approve or reject.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.common.targets import PROJECT_ROOT, relpath_from_root


DB_PATH = PROJECT_ROOT / "logs" / "openclaw" / "learning_candidates.db"
APPROVED_RULES_PATH = PROJECT_ROOT / "config" / "travel_learning_rules.json"
REPORT_PREFIX = "OpenClaw_rule_suggestions"
RECONSIDER_SEEN_COUNT = 5


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def desktop_dir() -> Path:
    candidate = Path.home() / "Desktop"
    return candidate if candidate.exists() else PROJECT_ROOT


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_text TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            seen_count INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            sample_image_path TEXT NOT NULL DEFAULT '',
            sample_folder TEXT NOT NULL DEFAULT '',
            original_classification TEXT NOT NULL DEFAULT '',
            original_reason TEXT NOT NULL DEFAULT '',
            decision_at TEXT,
            decision_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_learning_candidates_status
            ON learning_candidates(status, seen_count, last_seen_at);
        """
    )
    conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def clean_rule_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("<") and text.endswith(">"):
        return ""
    if len(text) < 2 or len(text) > 40:
        return ""
    return text


def candidate_rule_texts(sidecar: dict[str, Any]) -> list[str]:
    summary = sidecar.get("firstPassSummary") if isinstance(sidecar, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    values: list[object] = []
    values.extend(summary.get("countries") or [])
    values.extend(summary.get("regions") or [])
    values.extend(summary.get("features") or [])

    ocr = sidecar.get("ocr") if isinstance(sidecar, dict) else {}
    hits = str((ocr or {}).get("hits") or "")
    values.extend(part.strip() for part in hits.split(","))

    rules: list[str] = []
    seen: set[str] = set()
    for value in values:
        rule = clean_rule_text(value)
        if rule and rule not in seen:
            rules.append(rule)
            seen.add(rule)
    return rules


def folder_label_for_image(image_path: Path) -> str:
    parts = image_path.resolve().parts
    try:
        index = parts.index("download")
    except ValueError:
        return image_path.parent.name
    return parts[index + 1] if len(parts) > index + 1 else image_path.parent.name


def upsert_candidate(
    rule_text: str,
    *,
    sample_image_path: Path | str,
    sample_folder: str,
    original_classification: str,
    original_reason: str,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    rule = clean_rule_text(rule_text)
    if not rule:
        return None
    now = utc_now_iso()
    sample = relpath_from_root(Path(sample_image_path))
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO learning_candidates (
                rule_text, status, seen_count, first_seen_at, last_seen_at,
                sample_image_path, sample_folder, original_classification,
                original_reason
            ) VALUES (?, 'pending', 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_text) DO UPDATE SET
                seen_count = learning_candidates.seen_count + 1,
                last_seen_at = excluded.last_seen_at,
                sample_image_path = excluded.sample_image_path,
                sample_folder = excluded.sample_folder,
                original_classification = excluded.original_classification,
                original_reason = excluded.original_reason
            """,
            (
                rule,
                now,
                now,
                sample,
                sample_folder,
                original_classification,
                original_reason,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM learning_candidates WHERE rule_text = ?",
            (rule,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def record_assume_travel_candidates(
    image_path: Path,
    sidecar: dict[str, Any],
    *,
    original_classification: str,
    original_reason: str,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    if original_classification not in {"review", "other"}:
        return []
    sample_folder = folder_label_for_image(image_path)
    rows: list[dict[str, Any]] = []
    for rule in candidate_rule_texts(sidecar):
        row = upsert_candidate(
            rule,
            sample_image_path=image_path,
            sample_folder=sample_folder,
            original_classification=original_classification,
            original_reason=original_reason,
            db_path=db_path,
        )
        if row:
            rows.append(row)
    return rows


def list_candidates(
    *,
    include_reconsider: bool = True,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    where = "status = 'pending'"
    params: list[Any] = []
    if include_reconsider:
        where = f"({where} OR (status = 'rejected' AND seen_count >= ?))"
        params.append(RECONSIDER_SEEN_COUNT)
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM learning_candidates WHERE {where} "
            "ORDER BY status = 'rejected', seen_count DESC, last_seen_at DESC, id",
            params,
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def set_candidate_status(
    candidate_id: int,
    status: str,
    *,
    decision_by: str = "user",
    db_path: Path = DB_PATH,
    approved_rules_path: Path = APPROVED_RULES_PATH,
) -> dict[str, Any] | None:
    if status not in {"approved", "rejected"}:
        raise ValueError("status must be approved or rejected")
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            UPDATE learning_candidates
            SET status = ?, decision_at = ?, decision_by = ?
            WHERE id = ?
            """,
            (status, utc_now_iso(), decision_by.strip() or "user", int(candidate_id)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM learning_candidates WHERE id = ?",
            (int(candidate_id),),
        ).fetchone()
    if status == "approved":
        sync_approved_rules(db_path=db_path, output_path=approved_rules_path)
    return _row_to_dict(row) if row else None


def load_approved_rule_texts(path: Path = APPROVED_RULES_PATH) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rules = payload.get("rules") if isinstance(payload, dict) else []
    result: list[str] = []
    for item in rules or []:
        if isinstance(item, dict):
            rule = clean_rule_text(item.get("rule_text"))
        else:
            rule = clean_rule_text(item)
        if rule and rule not in result:
            result.append(rule)
    return result


def sync_approved_rules(
    *,
    db_path: Path = DB_PATH,
    output_path: Path = APPROVED_RULES_PATH,
) -> dict[str, Any]:
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT rule_text, decision_at
            FROM learning_candidates
            WHERE status = 'approved'
            ORDER BY rule_text
            """
        ).fetchall()
    payload = {
        "version": 1,
        "updated_at": utc_now_iso(),
        "rules": [
            {
                "rule_text": row["rule_text"],
                "approved_at": row["decision_at"] or "",
                "source": "manual_upload",
            }
            for row in rows
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(output_path)
    return payload


def render_report(candidates: list[dict[str, Any]] | None = None) -> str:
    rows = candidates if candidates is not None else list_candidates()
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# OpenClaw rule suggestions - {today}",
        "",
        "Manual uploads are trusted as travel images. These suggestions come from images",
        "that first-pass OCR would have routed to review/other.",
        "",
    ]
    if not rows:
        lines.extend(["No pending rule suggestions today.", ""])
        return "\n".join(lines)

    lines.extend([
        "| ID | Status | Rule | Seen | Original | Sample |",
        "| --- | --- | --- | ---: | --- | --- |",
    ])
    for row in rows:
        lines.append(
            "| {id} | {status} | {rule} | {seen} | {original} | {sample} |".format(
                id=row["id"],
                status=row["status"],
                rule=str(row["rule_text"]).replace("|", "\\|"),
                seen=row["seen_count"],
                original=f"{row['original_classification']} {row['original_reason']}".strip().replace("|", "\\|"),
                sample=str(row["sample_image_path"]).replace("|", "\\|"),
            )
        )
    lines.extend([
        "",
        "Commands:",
        "",
        "```powershell",
        "python -m tools.openclaw.learning_candidates approve <ID>",
        "python -m tools.openclaw.learning_candidates reject <ID>",
        "```",
        "",
    ])
    return "\n".join(lines)


def write_desktop_report(
    *,
    output_dir: Path | None = None,
    db_path: Path = DB_PATH,
) -> Path:
    out_dir = output_dir or desktop_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{REPORT_PREFIX}_{datetime.now().strftime('%Y-%m-%d')}.md"
    path.write_text(render_report(list_candidates(db_path=db_path)), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage OpenClaw travel learning candidates.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")
    sub.add_parser("report")
    sub.add_parser("sync")

    approve = sub.add_parser("approve")
    approve.add_argument("id", type=int)
    approve.add_argument("--by", default="user")

    reject = sub.add_parser("reject")
    reject.add_argument("id", type=int)
    reject.add_argument("--by", default="user")

    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps(list_candidates(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "report":
        path = write_desktop_report()
        print(str(path))
        return 0
    if args.command == "sync":
        print(json.dumps(sync_approved_rules(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "approve":
        row = set_candidate_status(args.id, "approved", decision_by=args.by)
        print(json.dumps(row or {}, ensure_ascii=False, indent=2))
        return 0 if row else 1
    if args.command == "reject":
        row = set_candidate_status(args.id, "rejected", decision_by=args.by)
        print(json.dumps(row or {}, ensure_ascii=False, indent=2))
        return 0 if row else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
