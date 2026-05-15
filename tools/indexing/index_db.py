"""SQLite wrapper for the travel itinerary index.

Single table, INSERT OR REPLACE keyed on sidecar_path. CSV fields (country,
months, airline, region, features) are wrapped in leading/trailing commas so
substring LIKE never accidentally matches '%4%' against '14'.

Schema version tracked via SQLite's PRAGMA user_version. On open, a mismatch
triggers DROP + recreate — acceptable because this DB is always rebuilt
from sidecars by `reindex.py`.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional


SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS itineraries (
    sidecar_path   TEXT PRIMARY KEY,
    image_path     TEXT NOT NULL,
    target_id      TEXT,
    group_name     TEXT,
    branded_path   TEXT,
    country_csv    TEXT,
    months_csv     TEXT,
    price_from     INTEGER,
    airline_csv    TEXT,
    region_csv     TEXT,
    duration_days  INTEGER,
    features_csv   TEXT,
    source_time    TEXT,
    indexed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_country  ON itineraries(country_csv);
CREATE INDEX IF NOT EXISTS idx_months   ON itineraries(months_csv);
CREATE INDEX IF NOT EXISTS idx_target   ON itineraries(target_id);
CREATE INDEX IF NOT EXISTS idx_airline  ON itineraries(airline_csv);
CREATE INDEX IF NOT EXISTS idx_region   ON itineraries(region_csv);
CREATE INDEX IF NOT EXISTS idx_duration ON itineraries(duration_days);

CREATE TABLE IF NOT EXISTS itinerary_plans (
    plan_id        TEXT PRIMARY KEY,
    sidecar_path   TEXT NOT NULL,
    image_path     TEXT NOT NULL,
    branded_path   TEXT,
    target_id      TEXT,
    group_name     TEXT,
    plan_no        INTEGER NOT NULL,
    title          TEXT,
    raw_text       TEXT,
    country_csv    TEXT,
    region_csv     TEXT,
    airline_csv    TEXT,
    features_csv   TEXT,
    months_csv     TEXT,
    price_from     INTEGER,
    duration_days  INTEGER,
    indexed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_sidecar  ON itinerary_plans(sidecar_path);
CREATE INDEX IF NOT EXISTS idx_plan_country  ON itinerary_plans(country_csv);
CREATE INDEX IF NOT EXISTS idx_plan_region   ON itinerary_plans(region_csv);
CREATE INDEX IF NOT EXISTS idx_plan_months   ON itinerary_plans(months_csv);
CREATE INDEX IF NOT EXISTS idx_plan_price    ON itinerary_plans(price_from);

CREATE TABLE IF NOT EXISTS itinerary_departures (
    departure_id   TEXT PRIMARY KEY,
    plan_id        TEXT NOT NULL,
    sidecar_path   TEXT NOT NULL,
    image_path     TEXT NOT NULL,
    branded_path   TEXT,
    target_id      TEXT,
    group_name     TEXT,
    departure_date TEXT NOT NULL,
    date_text      TEXT,
    month          INTEGER NOT NULL,
    day            INTEGER NOT NULL,
    weekday        INTEGER NOT NULL,
    price_from     INTEGER,
    duration_days  INTEGER,
    indexed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dep_plan     ON itinerary_departures(plan_id);
CREATE INDEX IF NOT EXISTS idx_dep_date     ON itinerary_departures(departure_date);
CREATE INDEX IF NOT EXISTS idx_dep_weekday  ON itinerary_departures(weekday);
CREATE INDEX IF NOT EXISTS idx_dep_month    ON itinerary_departures(month);
CREATE INDEX IF NOT EXISTS idx_dep_target   ON itinerary_departures(target_id);
"""


COLUMNS = (
    "sidecar_path", "image_path", "target_id", "group_name", "branded_path",
    "country_csv", "months_csv", "price_from",
    "airline_csv", "region_csv", "duration_days", "features_csv",
    "source_time", "indexed_at",
)
_INSERT_SQL = (
    f"INSERT OR REPLACE INTO itineraries ({', '.join(COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(COLUMNS))})"
)

PLAN_COLUMNS = (
    "plan_id", "sidecar_path", "image_path", "branded_path", "target_id",
    "group_name", "plan_no", "title", "raw_text", "country_csv",
    "region_csv", "airline_csv", "features_csv", "months_csv",
    "price_from", "duration_days", "indexed_at",
)
_INSERT_PLAN_SQL = (
    f"INSERT OR REPLACE INTO itinerary_plans ({', '.join(PLAN_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(PLAN_COLUMNS))})"
)

DEPARTURE_COLUMNS = (
    "departure_id", "plan_id", "sidecar_path", "image_path", "branded_path",
    "target_id", "group_name", "departure_date", "date_text", "month", "day",
    "weekday", "price_from", "duration_days", "indexed_at",
)
_INSERT_DEPARTURE_SQL = (
    f"INSERT OR REPLACE INTO itinerary_departures ({', '.join(DEPARTURE_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(DEPARTURE_COLUMNS))})"
)


def _wrap_csv(values: Iterable[Any]) -> Optional[str]:
    """Encode a list as ',a,b,c,' so LIKE '%,a,%' works for exact token match."""
    items = [str(v) for v in values if v is not None and str(v) != ""]
    if not items:
        return None
    return "," + ",".join(items) + ","


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TravelIndex:
    def __init__(self, db_path: Path | str, migrate: bool = True):
        """Open (or create) the index DB.

        migrate=True  (default, used by reindex.py): if the existing DB has
            a mismatched user_version, DROP and recreate the table. Safe
            because reindex rebuilds from source sidecars.
        migrate=False (used by filter.py auto wrapper): raise on version
            mismatch instead of dropping. Prevents accidental data loss
            from a long-running writer encountering a new schema.
        """
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._autocommit = True

        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if current == SCHEMA_VERSION:
            self.conn.executescript(SCHEMA)
            self.conn.commit()
            return

        table_exists = self.conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='itineraries'"
        ).fetchone() is not None

        if not table_exists:
            self.conn.executescript(SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()
            return

        if migrate:
            self.conn.executescript(
                "DROP TABLE IF EXISTS itinerary_departures;"
                "DROP TABLE IF EXISTS itinerary_plans;"
                "DROP TABLE IF EXISTS itineraries;"
            )
            self.conn.executescript(SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()
        else:
            self.conn.close()
            raise RuntimeError(
                f"DB schema version {current} != expected {SCHEMA_VERSION}. "
                f"Run `python tools/indexing/reindex.py` to rebuild."
            )

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _maybe_commit(self) -> None:
        if self._autocommit:
            self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator["TravelIndex"]:
        """Batch mode: suspend per-write commits and commit once on exit.

        Roughly 100x faster than per-row commit for bulk reindex (fsync per
        commit is the bottleneck). On exception, rolls back all pending work.
        """
        was_auto = self._autocommit
        self._autocommit = False
        try:
            yield self
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        finally:
            self._autocommit = was_auto

    # -- writes --------------------------------------------------------------

    def upsert(
        self,
        *,
        sidecar_path: str,
        image_path: str,
        target_id: Optional[str] = None,
        group_name: Optional[str] = None,
        branded_path: Optional[str] = None,
        countries: Optional[Iterable[str]] = None,
        months: Optional[Iterable[int]] = None,
        price_from: Optional[int] = None,
        airlines: Optional[Iterable[str]] = None,
        regions: Optional[Iterable[str]] = None,
        duration_days: Optional[int] = None,
        features: Optional[Iterable[str]] = None,
        source_time: Optional[str] = None,
    ) -> None:
        """Insert or replace a row, keyed by sidecar_path."""
        row = (
            sidecar_path,
            image_path,
            target_id,
            group_name,
            branded_path,
            _wrap_csv(countries or ()),
            _wrap_csv(months or ()),
            int(price_from) if price_from is not None else None,
            _wrap_csv(airlines or ()),
            _wrap_csv(regions or ()),
            int(duration_days) if duration_days is not None else None,
            _wrap_csv(features or ()),
            source_time,
            _iso_now(),
        )
        self.conn.execute(_INSERT_SQL, row)
        self._maybe_commit()

    def upsert_plan(
        self,
        *,
        plan_id: str,
        sidecar_path: str,
        image_path: str,
        branded_path: Optional[str] = None,
        target_id: Optional[str] = None,
        group_name: Optional[str] = None,
        plan_no: int,
        title: Optional[str] = None,
        raw_text: Optional[str] = None,
        countries: Optional[Iterable[str]] = None,
        regions: Optional[Iterable[str]] = None,
        airlines: Optional[Iterable[str]] = None,
        features: Optional[Iterable[str]] = None,
        months: Optional[Iterable[int]] = None,
        price_from: Optional[int] = None,
        duration_days: Optional[int] = None,
    ) -> None:
        row = (
            plan_id, sidecar_path, image_path, branded_path, target_id,
            group_name, int(plan_no), title, raw_text,
            _wrap_csv(countries or ()), _wrap_csv(regions or ()),
            _wrap_csv(airlines or ()), _wrap_csv(features or ()),
            _wrap_csv(months or ()),
            int(price_from) if price_from is not None else None,
            int(duration_days) if duration_days is not None else None,
            _iso_now(),
        )
        self.conn.execute(_INSERT_PLAN_SQL, row)
        self._maybe_commit()

    def upsert_departure(
        self,
        *,
        departure_id: str,
        plan_id: str,
        sidecar_path: str,
        image_path: str,
        branded_path: Optional[str] = None,
        target_id: Optional[str] = None,
        group_name: Optional[str] = None,
        departure_date: str,
        date_text: Optional[str] = None,
        month: int,
        day: int,
        weekday: int,
        price_from: Optional[int] = None,
        duration_days: Optional[int] = None,
    ) -> None:
        row = (
            departure_id, plan_id, sidecar_path, image_path, branded_path,
            target_id, group_name, departure_date, date_text, int(month),
            int(day), int(weekday),
            int(price_from) if price_from is not None else None,
            int(duration_days) if duration_days is not None else None,
            _iso_now(),
        )
        self.conn.execute(_INSERT_DEPARTURE_SQL, row)
        self._maybe_commit()

    def delete(self, sidecar_path: str) -> None:
        self.conn.execute(
            "DELETE FROM itinerary_departures WHERE sidecar_path = ?", (sidecar_path,)
        )
        self.conn.execute(
            "DELETE FROM itinerary_plans WHERE sidecar_path = ?", (sidecar_path,)
        )
        self.conn.execute(
            "DELETE FROM itineraries WHERE sidecar_path = ?", (sidecar_path,)
        )
        self._maybe_commit()

    def clear(self) -> None:
        self.conn.execute("DELETE FROM itinerary_departures")
        self.conn.execute("DELETE FROM itinerary_plans")
        self.conn.execute("DELETE FROM itineraries")
        self._maybe_commit()

    # -- reads ---------------------------------------------------------------

    def count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM itineraries")
        return int(cur.fetchone()[0])

    def plan_count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM itinerary_plans")
        return int(cur.fetchone()[0])

    def departure_count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM itinerary_departures")
        return int(cur.fetchone()[0])

    def query(
        self,
        *,
        countries: Optional[Iterable[str]] = None,
        months: Optional[Iterable[int]] = None,
        price_min: Optional[int] = None,
        price_max: Optional[int] = None,
        airlines: Optional[Iterable[str]] = None,
        regions: Optional[Iterable[str]] = None,
        duration_days: Optional[int] = None,
        duration_min: Optional[int] = None,
        duration_max: Optional[int] = None,
        features: Optional[Iterable[str]] = None,
        target_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Filter itineraries by any combination of fields.

        CSV field filters (countries / months / airlines / regions / features)
        are all any-of matches — a row qualifies if at least one token overlaps.
        Numeric filters (price_min/max, duration_*) are range filters.
        Returns rows as dicts ordered by indexed_at DESC.
        """
        clauses: list[str] = []
        params: list[Any] = []

        def add_csv_any(column: str, values: Optional[Iterable[Any]]) -> None:
            if not values:
                return
            value_list = list(values)
            if not value_list:
                return
            like_parts = " OR ".join(f"{column} LIKE ?" for _ in value_list)
            clauses.append(f"({like_parts})")
            params.extend(f"%,{v},%" for v in value_list)

        add_csv_any("country_csv", countries)
        add_csv_any("months_csv", months)
        add_csv_any("airline_csv", airlines)
        add_csv_any("region_csv", regions)
        add_csv_any("features_csv", features)

        if price_min is not None:
            clauses.append("price_from >= ?")
            params.append(int(price_min))
        if price_max is not None:
            clauses.append("price_from <= ?")
            params.append(int(price_max))

        if duration_days is not None:
            clauses.append("duration_days = ?")
            params.append(int(duration_days))
        if duration_min is not None:
            clauses.append("duration_days >= ?")
            params.append(int(duration_min))
        if duration_max is not None:
            clauses.append("duration_days <= ?")
            params.append(int(duration_max))

        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM itineraries {where} "
            f"ORDER BY indexed_at DESC LIMIT ?"
        )
        params.append(int(limit))

        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
