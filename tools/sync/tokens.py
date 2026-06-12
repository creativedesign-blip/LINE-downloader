from __future__ import annotations

from typing import Any

from tools.sync.models import Row


def csv_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _add(
    rows: list[Row],
    *,
    itinerary_id: str | None,
    asset_id: str | None,
    source_kind: str,
    token_type: str,
    token_value: Any,
    normalized_token: Any | None = None,
    source_field: str,
    weight: int = 1,
) -> None:
    if token_value is None or str(token_value).strip() == "":
        return
    norm = token_value if normalized_token is None else normalized_token
    if norm is None or str(norm).strip() == "":
        return
    rows.append(
        {
            "itinerary_id": itinerary_id,
            "asset_id": asset_id,
            "source_kind": source_kind,
            "token_type": token_type,
            "token_value": str(token_value).strip(),
            "normalized_token": str(norm).strip(),
            "source_field": source_field,
            "confidence": 1.0,
            "weight": weight,
        }
    )


def tokens_for_itinerary(row: Row) -> list[Row]:
    source_kind = str(row.get("source_kind") or "")
    itinerary_id = row.get("itinerary_id")
    asset_id = row.get("asset_id")
    out: list[Row] = []
    for value in csv_tokens(row.get("country_csv")):
        _add(
            out,
            itinerary_id=itinerary_id,
            asset_id=asset_id,
            source_kind=source_kind,
            token_type="country",
            token_value=value,
            source_field="country_csv",
            weight=4,
        )
    for value in csv_tokens(row.get("region_csv")):
        _add(
            out,
            itinerary_id=itinerary_id,
            asset_id=asset_id,
            source_kind=source_kind,
            token_type="region",
            token_value=value,
            source_field="region_csv",
            weight=3,
        )
    for value in csv_tokens(row.get("features_csv")):
        _add(
            out,
            itinerary_id=itinerary_id,
            asset_id=asset_id,
            source_kind=source_kind,
            token_type="feature",
            token_value=value,
            source_field="features_csv",
            weight=2,
        )
    for value in csv_tokens(row.get("months_csv")):
        if value.isdigit():
            _add(
                out,
                itinerary_id=itinerary_id,
                asset_id=asset_id,
                source_kind=source_kind,
                token_type="month",
                token_value=value,
                normalized_token=int(value),
                source_field="months_csv",
                weight=3,
            )
    if row.get("duration_days") is not None:
        _add(
            out,
            itinerary_id=itinerary_id,
            asset_id=asset_id,
            source_kind=source_kind,
            token_type="duration",
            token_value=row.get("duration_days"),
            normalized_token=row.get("duration_days"),
            source_field="duration_days",
            weight=3,
        )
    if row.get("price_from_twd") is not None:
        _add(
            out,
            itinerary_id=itinerary_id,
            asset_id=asset_id,
            source_kind=source_kind,
            token_type="price",
            token_value=row.get("price_from_twd"),
            normalized_token=row.get("price_from_twd"),
            source_field="price_from_twd",
            weight=2,
        )
    for field in ("product_title", "group_name"):
        value = row.get(field)
        if value:
            _add(
                out,
                itinerary_id=itinerary_id,
                asset_id=asset_id,
                source_kind=source_kind,
                token_type="raw_ocr_keyword",
                token_value=value,
                source_field=field,
            )
    return out


def dedupe_tokens(rows: list[Row]) -> list[Row]:
    seen: set[tuple[Any, ...]] = set()
    out: list[Row] = []
    for row in rows:
        key = (
            row.get("itinerary_id"),
            row.get("asset_id"),
            row.get("token_type"),
            row.get("normalized_token"),
            row.get("source_field"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
