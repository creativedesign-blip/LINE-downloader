from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.sync.models import AssetMedia, Row, SyncDataset
from tools.sync.source_readers import resolve_project_path
from tools.sync.tokens import csv_tokens, dedupe_tokens, tokens_for_itinerary


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _first_path(*values: Any) -> str:
    for value in values:
        if value:
            return str(value)
    return ""


def _status_for_path(path_value: str) -> str:
    if not path_value:
        return "missing_file"
    resolved = resolve_project_path(path_value)
    return "pending" if resolved and resolved.is_file() else "missing_file"


def _destination_text(*parts: Any) -> str:
    tokens: list[str] = []
    for part in parts:
        tokens.extend(csv_tokens(part))
        if part and not str(part).startswith(","):
            tokens.append(str(part))
    return " ".join(dict.fromkeys(item.strip() for item in tokens if item.strip()))


def _media_candidate(asset_id: str, source_kind: str, source_path: str) -> AssetMedia:
    file_path = resolve_project_path(source_path)
    return AssetMedia(
        asset_id=asset_id,
        source_kind=source_kind,
        source_path=source_path,
        file_path=file_path if file_path and file_path.is_file() else None,
    )


def build_dataset(
    travel: dict[str, list[Row]],
    upload: dict[str, list[Row]],
    *,
    limit: int | None = None,
) -> SyncDataset:
    warnings: list[str] = []
    assets: list[Row] = []
    itineraries: list[Row] = []
    departures: list[Row] = []
    upload_folders: list[Row] = []
    manual_tags: list[Row] = []
    media: list[AssetMedia] = []
    tokens: list[Row] = []
    now = utc_now_iso()

    travel_itineraries = travel.get("itineraries", [])
    travel_plans = travel.get("itinerary_plans", [])
    travel_departures = travel.get("itinerary_departures", [])
    if limit is not None:
        travel_itineraries = travel_itineraries[:limit]
        travel_plans = travel_plans[:limit]
        travel_departures = travel_departures[: max(limit * 5, limit)]

    asset_seen: set[str] = set()
    for row in travel_itineraries:
        asset_id = str(row.get("sidecar_path") or "")
        if not asset_id:
            continue
        source_path = _first_path(row.get("branded_path"), row.get("image_path"))
        asset = {
            "asset_id": asset_id,
            "source_kind": "travel_index",
            "source_table": "itineraries",
            "source_pk": asset_id,
            "image_path": row.get("image_path"),
            "branded_path": row.get("branded_path"),
            "stored_path": None,
            "image_sha256": row.get("image_sha256"),
            "image_phash": row.get("image_phash"),
            "crm_media_id": None,
            "crm_media_url": None,
            "public_image_url": None,
            "crm_media_status": _status_for_path(source_path),
            "crm_media_uploaded_at": None,
            "crm_media_error": None,
            "status": "active",
            "source_time": row.get("source_time"),
            "indexed_at": row.get("indexed_at"),
            "updated_at": now,
        }
        assets.append(asset)
        asset_seen.add(asset_id)
        if source_path:
            media.append(_media_candidate(asset_id, "travel_index", source_path))
        else:
            warnings.append(f"travel asset missing image path: {asset_id}")

    for row in travel_plans:
        itinerary_id = str(row.get("plan_id") or "")
        if not itinerary_id:
            continue
        item = {
            "itinerary_id": itinerary_id,
            "asset_id": row.get("sidecar_path"),
            "source_kind": "travel_index",
            "source_table": "itinerary_plans",
            "source_pk": itinerary_id,
            "product_title": row.get("title"),
            "group_name": row.get("group_name"),
            "country_csv": row.get("country_csv"),
            "region_csv": row.get("region_csv"),
            "destination_text": _destination_text(
                row.get("country_csv"), row.get("region_csv"), row.get("title")
            ),
            "features_csv": row.get("features_csv"),
            "months_csv": row.get("months_csv"),
            "price_from_twd": row.get("price_from"),
            "duration_days": row.get("duration_days"),
            "raw_text": row.get("raw_text"),
            "crm_media_url": None,
            "public_image_url": None,
            "branded_path": row.get("branded_path"),
            "status": "active",
            "indexed_at": row.get("indexed_at"),
            "updated_at": now,
        }
        itineraries.append(item)
        tokens.extend(tokens_for_itinerary(item))

    for row in travel_departures:
        dep_id = str(row.get("departure_id") or "")
        if not dep_id:
            continue
        departures.append(
            {
                "departure_id": dep_id,
                "itinerary_id": row.get("plan_id"),
                "asset_id": row.get("sidecar_path"),
                "source_kind": "travel_index",
                "departure_date": row.get("departure_date"),
                "date_text": row.get("date_text"),
                "month": row.get("month"),
                "day": row.get("day"),
                "weekday": row.get("weekday"),
                "price_from_twd": row.get("price_from"),
                "duration_days": row.get("duration_days"),
                "crm_media_url": None,
                "public_image_url": None,
                "status": "active",
                "indexed_at": row.get("indexed_at"),
                "updated_at": now,
            }
        )

    folders_by_id = {int(row["id"]): row for row in upload.get("upload_folders", []) if row.get("id") is not None}
    search_by_image = {
        int(row["image_id"]): row
        for row in upload.get("uploaded_image_search_index", [])
        if row.get("image_id") is not None
    }
    upload_images = upload.get("uploaded_images", [])
    if limit is not None:
        upload_images = upload_images[:limit]
    for row in upload.get("upload_folders", [])[: limit or None]:
        upload_folders.append(
            {
                "folder_id": row.get("id"),
                "folder_slug": row.get("folder_slug"),
                "display_name": row.get("display_name"),
                "note": row.get("note"),
                "source": row.get("source"),
                "status": row.get("status"),
                "current_step": row.get("current_step"),
                "image_count": row.get("image_count"),
                "line_groups_json": row.get("line_groups"),
                "captured_at": row.get("captured_at"),
                "job_id": row.get("job_id"),
                "archived_at": row.get("archived_at"),
                "archived_by": row.get("archived_by"),
                "delete_after": row.get("delete_after"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )

    for row in upload_images:
        image_id = int(row.get("id"))
        asset_id = f"upload_catalog:image:{image_id}"
        search = search_by_image.get(image_id, {})
        source_path = _first_path(
            search.get("branded_path"), search.get("image_path"), row.get("stored_path")
        )
        folder = folders_by_id.get(int(row.get("folder_id") or 0), {})
        assets.append(
            {
                "asset_id": asset_id,
                "source_kind": "upload_catalog",
                "source_table": "uploaded_images",
                "source_pk": str(image_id),
                "image_path": search.get("image_path"),
                "branded_path": search.get("branded_path"),
                "stored_path": row.get("stored_path"),
                "image_sha256": row.get("sha256"),
                "image_phash": None,
                "crm_media_id": None,
                "crm_media_url": None,
                "public_image_url": None,
                "crm_media_status": _status_for_path(source_path),
                "crm_media_uploaded_at": None,
                "crm_media_error": None,
                "status": "archived" if row.get("archived_at") else "active",
                "source_time": search.get("source_time") or row.get("uploaded_at"),
                "indexed_at": search.get("indexed_at"),
                "updated_at": now,
            }
        )
        if source_path:
            media.append(_media_candidate(asset_id, "upload_catalog", source_path))
        else:
            warnings.append(f"upload asset missing image path: {asset_id}")
        if search:
            itinerary_id = f"upload_catalog:index:{image_id}"
            item = {
                "itinerary_id": itinerary_id,
                "asset_id": asset_id,
                "source_kind": "upload_catalog",
                "source_table": "uploaded_image_search_index",
                "source_pk": str(image_id),
                "product_title": row.get("display_name") or row.get("original_filename"),
                "group_name": folder.get("display_name"),
                "country_csv": search.get("country_csv"),
                "region_csv": search.get("region_csv"),
                "destination_text": _destination_text(
                    search.get("country_csv"),
                    search.get("region_csv"),
                    row.get("display_name"),
                    row.get("original_filename"),
                ),
                "features_csv": search.get("features_csv"),
                "months_csv": search.get("months_csv"),
                "price_from_twd": search.get("price_from"),
                "duration_days": search.get("duration_days"),
                "raw_text": search.get("raw_text") or search.get("search_text"),
                "crm_media_url": None,
                "public_image_url": None,
                "branded_path": search.get("branded_path"),
                "status": "archived" if row.get("archived_at") else "active",
                "indexed_at": search.get("indexed_at"),
                "updated_at": now,
            }
            itineraries.append(item)
            tokens.extend(tokens_for_itinerary(item))
        else:
            warnings.append(f"upload image missing search index: {asset_id}")

    for row in upload.get("manual_tags", [])[: limit or None]:
        image_id = row.get("image_id")
        asset_id = f"upload_catalog:image:{image_id}" if image_id is not None else None
        manual_tags.append(
            {
                "tag_id": row.get("id"),
                "asset_id": asset_id,
                "upload_image_id": image_id,
                "tag": row.get("tag"),
                "note": row.get("note"),
                "created_by": row.get("created_by"),
                "created_at": row.get("created_at"),
            }
        )
        if row.get("tag"):
            tokens.append(
                {
                    "itinerary_id": f"upload_catalog:index:{image_id}" if image_id else None,
                    "asset_id": asset_id,
                    "source_kind": "upload_catalog",
                    "token_type": "manual_tag",
                    "token_value": str(row.get("tag")).strip(),
                    "normalized_token": str(row.get("tag")).strip(),
                    "source_field": "manual_tags.tag",
                    "confidence": 1.0,
                    "weight": 5,
                }
            )

    return SyncDataset(
        assets=assets,
        itineraries=itineraries,
        departures=departures,
        search_tokens=dedupe_tokens(tokens),
        upload_folders=upload_folders,
        manual_tags=manual_tags,
        media=media,
        warnings=warnings,
    )
