from __future__ import annotations

from typing import Any

from tools.sync.config import SyncConfig
from tools.sync.models import Row


TABLE_COLUMNS: dict[str, list[str]] = {
    "crm_assets": [
        "asset_id", "source_kind", "source_table", "source_pk", "image_path",
        "branded_path", "stored_path", "image_sha256", "image_phash",
        "crm_media_id", "crm_media_url", "public_image_url", "crm_media_status",
        "crm_media_uploaded_at", "crm_media_error", "status", "source_time",
        "indexed_at", "updated_at",
    ],
    "crm_itineraries": [
        "itinerary_id", "asset_id", "source_kind", "source_table", "source_pk",
        "product_title", "group_name", "country_csv", "region_csv",
        "destination_text", "features_csv", "months_csv", "price_from_twd",
        "duration_days", "raw_text", "crm_media_url", "public_image_url",
        "branded_path", "status", "indexed_at", "updated_at",
    ],
    "crm_departures": [
        "departure_id", "itinerary_id", "asset_id", "source_kind",
        "departure_date", "date_text", "month", "day", "weekday",
        "price_from_twd", "duration_days", "crm_media_url", "public_image_url",
        "status", "indexed_at", "updated_at",
    ],
    "crm_search_tokens": [
        "itinerary_id", "asset_id", "source_kind", "token_type", "token_value",
        "normalized_token", "source_field", "confidence", "weight",
    ],
    "crm_upload_folders": [
        "folder_id", "folder_slug", "display_name", "note", "source", "status",
        "current_step", "image_count", "line_groups_json", "captured_at",
        "job_id", "archived_at", "archived_by", "delete_after", "created_at",
        "updated_at",
    ],
    "crm_manual_tags": [
        "tag_id", "asset_id", "upload_image_id", "tag", "note", "created_by",
        "created_at",
    ],
}

PRIMARY_KEYS = {
    "crm_assets": "asset_id",
    "crm_itineraries": "itinerary_id",
    "crm_departures": "departure_id",
    "crm_upload_folders": "folder_id",
    "crm_manual_tags": "tag_id",
}

STATUS_TABLES = {
    "crm_assets": "asset_id",
    "crm_itineraries": "itinerary_id",
    "crm_departures": "departure_id",
}

DELETE_STALE_TABLES = {
    "crm_upload_folders": "folder_id",
    "crm_manual_tags": "tag_id",
}


class MySQLWriter:
    def __init__(self, config: SyncConfig):
        self.config = config
        self.conn: Any = None

    def connect(self) -> None:
        import pymysql  # type: ignore

        self.conn = pymysql.connect(
            host=self.config.mysql_host,
            port=self.config.mysql_port,
            user=self.config.mysql_user,
            password=self.config.mysql_password,
            database=self.config.mysql_db,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def preflight(self) -> None:
        if self.conn is None:
            raise RuntimeError("MySQLWriter is not connected")
        expected = set(TABLE_COLUMNS)
        expected.add("crm_sync_status")
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name LIKE 'crm\\_%%'
                """,
                (self.config.mysql_db,),
            )
            found = {row["TABLE_NAME"] if "TABLE_NAME" in row else row["table_name"] for row in cur.fetchall()}
            missing_tables = expected - found
            if missing_tables:
                raise RuntimeError(f"missing CRM tables: {sorted(missing_tables)}")
            cur.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name LIKE 'crm\\_%%'
                """,
                (self.config.mysql_db,),
            )
            by_table: dict[str, set[str]] = {}
            for row in cur.fetchall():
                table = row.get("TABLE_NAME") or row.get("table_name")
                col = row.get("COLUMN_NAME") or row.get("column_name")
                by_table.setdefault(str(table), set()).add(str(col))
        for table, columns in TABLE_COLUMNS.items():
            missing_cols = set(columns) - by_table.get(table, set())
            if missing_cols:
                raise RuntimeError(f"{table} missing columns: {sorted(missing_cols)}")
        if "token_uniq_hash" not in by_table.get("crm_search_tokens", set()):
            raise RuntimeError("crm_search_tokens.token_uniq_hash generated column is missing")

    def upsert_many(self, table: str, rows: list[Row]) -> int:
        if self.conn is None:
            raise RuntimeError("MySQLWriter is not connected")
        if not rows:
            return 0
        sql, params = build_upsert_sql(table, rows)
        with self.conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def begin(self) -> None:
        if self.conn is None:
            raise RuntimeError("MySQLWriter is not connected")
        self.conn.begin()

    def commit(self) -> None:
        if self.conn is None:
            raise RuntimeError("MySQLWriter is not connected")
        self.conn.commit()

    def rollback(self) -> None:
        if self.conn is not None:
            self.conn.rollback()

    def replace_search_tokens(self, rows: list[Row]) -> int:
        if self.conn is None:
            raise RuntimeError("MySQLWriter is not connected")
        source_kinds = sorted({str(row.get("source_kind") or "") for row in rows if row.get("source_kind")})
        if not source_kinds:
            return 0
        placeholders = ", ".join(["%s"] * len(source_kinds))
        with self.conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM `crm_search_tokens` WHERE `source_kind` IN ({placeholders})",
                tuple(source_kinds),
            )
        return self.upsert_many("crm_search_tokens", rows)

    def mark_missing_inactive(self, table: str, source_kind: str, current_keys: set[str], updated_at: str) -> int:
        if self.conn is None:
            raise RuntimeError("MySQLWriter is not connected")
        pk = STATUS_TABLES[table]
        if not current_keys:
            return 0
        placeholders = ", ".join(["%s"] * len(current_keys))
        sql = (
            f"UPDATE `{table}` SET `status` = 'inactive', `updated_at` = %s "
            f"WHERE `source_kind` = %s AND `{pk}` NOT IN ({placeholders}) "
            "AND (`status` IS NULL OR `status` <> 'inactive')"
        )
        with self.conn.cursor() as cur:
            cur.execute(sql, (updated_at, source_kind, *sorted(current_keys)))
            return int(cur.rowcount or 0)

    def delete_missing(self, table: str, current_keys: set[str]) -> int:
        if self.conn is None:
            raise RuntimeError("MySQLWriter is not connected")
        pk = DELETE_STALE_TABLES[table]
        if not current_keys:
            return 0
        placeholders = ", ".join(["%s"] * len(current_keys))
        with self.conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM `{table}` WHERE `{pk}` NOT IN ({placeholders})",
                tuple(sorted(current_keys)),
            )
            return int(cur.rowcount or 0)


def build_upsert_sql(table: str, rows: list[Row]) -> tuple[str, list[tuple[Any, ...]]]:
    if table not in TABLE_COLUMNS:
        raise ValueError(f"unknown CRM table: {table}")
    columns = TABLE_COLUMNS[table]
    placeholders = ", ".join(["%s"] * len(columns))
    quoted = ", ".join(f"`{col}`" for col in columns)
    updates = ", ".join(f"`{col}` = VALUES(`{col}`)" for col in columns if col != PRIMARY_KEYS.get(table))
    if table == "crm_search_tokens":
        updates = ", ".join(
            f"`{col}` = VALUES(`{col}`)" for col in columns if col not in {"itinerary_id", "asset_id", "token_type", "normalized_token", "source_field"}
        )
    sql = f"INSERT INTO `{table}` ({quoted}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"
    params = [tuple(row.get(col) for col in columns) for row in rows]
    return sql, params


class FakeMySQLWriter:
    def __init__(self) -> None:
        self.rows: dict[str, list[Row]] = {}
        self.committed = False
        self.rolled_back = False

    def begin(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def upsert_many(self, table: str, rows: list[Row]) -> int:
        self.rows.setdefault(table, []).extend(rows)
        return len(rows)

    def replace_search_tokens(self, rows: list[Row]) -> int:
        self.rows["crm_search_tokens"] = list(rows)
        return len(rows)

    def mark_missing_inactive(self, table: str, source_kind: str, current_keys: set[str], updated_at: str) -> int:
        return 0

    def delete_missing(self, table: str, current_keys: set[str]) -> int:
        return 0
