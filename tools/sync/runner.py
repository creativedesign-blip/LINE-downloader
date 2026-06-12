from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any

from tools.sync.config import SyncConfig
from tools.sync.media_uploader import FakeMediaUploader, MediaUploader, file_sha256
from tools.sync.models import MediaResult, SyncDataset
from tools.sync.mysql_writer import FakeMySQLWriter, MySQLWriter
from tools.sync.source_readers import read_travel_index, read_upload_catalog
from tools.sync.transform import build_dataset, utc_now_iso
from tools.sync import meta
from tools.sync.tunnel import SSHTunnel


def build_current_dataset(limit: int | None = None) -> SyncDataset:
    return build_dataset(read_travel_index(), read_upload_catalog(), limit=limit)


def dry_run(limit: int | None = None) -> dict[str, Any]:
    dataset = build_current_dataset(limit=limit)
    return {
        "ok": True,
        "dry_run": True,
        "counts": dataset.counts(),
        "warnings": dataset.warnings[:50],
    }


def apply_media_results(dataset: SyncDataset, results: dict[str, MediaResult]) -> None:
    by_asset = {media.asset_id: results.get(media.asset_id) for media in dataset.media}
    for asset in dataset.assets:
        result = by_asset.get(str(asset.get("asset_id")))
        if result is None:
            continue
        asset["crm_media_id"] = result.media_id
        asset["crm_media_url"] = result.url
        asset["public_image_url"] = result.url
        asset["crm_media_status"] = "uploaded"
        asset["crm_media_uploaded_at"] = utc_now_iso()
        asset["crm_media_error"] = None
    for row in dataset.itineraries:
        result = by_asset.get(str(row.get("asset_id")))
        if result is not None:
            row["crm_media_url"] = result.url
            row["public_image_url"] = result.url
    for row in dataset.departures:
        result = by_asset.get(str(row.get("asset_id")))
        if result is not None:
            row["crm_media_url"] = result.url
            row["public_image_url"] = result.url


def upload_media(
    dataset: SyncDataset,
    uploader: Any,
    *,
    use_cache: bool = True,
) -> dict[str, MediaResult]:
    results: dict[str, MediaResult] = {}
    seen_sha: dict[str, MediaResult] = {}
    now = utc_now_iso()
    for media in dataset.media:
        if media.file_path is None:
            continue
        sha = file_sha256(media.file_path)
        cached = meta.get_media(sha) if use_cache else None
        if cached is not None:
            results[media.asset_id] = cached
            seen_sha[sha] = cached
            continue
        if sha in seen_sha:
            results[media.asset_id] = seen_sha[sha]
            continue
        result = uploader.upload(media)
        if use_cache:
            meta.save_media(result, uploaded_at=now)
        results[media.asset_id] = result
        seen_sha[sha] = result
    return results


def write_dataset(dataset: SyncDataset, writer: Any) -> dict[str, int]:
    now = utc_now_iso()
    counts: dict[str, int] = {}
    writer.begin()
    try:
        counts["crm_assets"] = writer.upsert_many("crm_assets", dataset.assets)
        counts["crm_itineraries"] = writer.upsert_many("crm_itineraries", dataset.itineraries)
        counts["crm_departures"] = writer.upsert_many("crm_departures", dataset.departures)
        counts["crm_upload_folders"] = writer.upsert_many("crm_upload_folders", dataset.upload_folders)
        counts["crm_manual_tags"] = writer.upsert_many("crm_manual_tags", dataset.manual_tags)
        counts["crm_search_tokens"] = writer.replace_search_tokens(dataset.search_tokens)

        for source_kind in ("travel_index", "upload_catalog"):
            asset_keys = {
                str(row["asset_id"])
                for row in dataset.assets
                if row.get("source_kind") == source_kind and row.get("asset_id")
            }
            itinerary_keys = {
                str(row["itinerary_id"])
                for row in dataset.itineraries
                if row.get("source_kind") == source_kind and row.get("itinerary_id")
            }
            departure_keys = {
                str(row["departure_id"])
                for row in dataset.departures
                if row.get("source_kind") == source_kind and row.get("departure_id")
            }
            counts[f"crm_assets_inactivated_{source_kind}"] = writer.mark_missing_inactive(
                "crm_assets", source_kind, asset_keys, now
            )
            counts[f"crm_itineraries_inactivated_{source_kind}"] = writer.mark_missing_inactive(
                "crm_itineraries", source_kind, itinerary_keys, now
            )
            counts[f"crm_departures_inactivated_{source_kind}"] = writer.mark_missing_inactive(
                "crm_departures", source_kind, departure_keys, now
            )

        folder_keys = {str(row["folder_id"]) for row in dataset.upload_folders if row.get("folder_id") is not None}
        tag_keys = {str(row["tag_id"]) for row in dataset.manual_tags if row.get("tag_id") is not None}
        counts["crm_upload_folders_deleted"] = writer.delete_missing("crm_upload_folders", folder_keys)
        counts["crm_manual_tags_deleted"] = writer.delete_missing("crm_manual_tags", tag_keys)
        writer.commit()
    except Exception:
        writer.rollback()
        raise
    return counts


def run_fake(limit: int | None = None) -> dict[str, Any]:
    dataset = build_current_dataset(limit=limit)
    media_results = upload_media(dataset, FakeMediaUploader(), use_cache=False)
    apply_media_results(dataset, media_results)
    writer = FakeMySQLWriter()
    written = write_dataset(dataset, writer)
    return {
        "ok": True,
        "fake": True,
        "counts": dataset.counts(),
        "media_uploaded": len(media_results),
        "written": written,
        "warnings": dataset.warnings[:50],
    }


def run_sync(limit: int | None = None) -> dict[str, Any]:
    cfg = SyncConfig.from_env()
    missing = sorted(set(cfg.missing_for_media() + cfg.missing_for_mysql()))
    if missing:
        return {"ok": False, "error": f"missing env: {', '.join(missing)}"}

    dataset = build_current_dataset(limit=limit)
    media_results = upload_media(dataset, MediaUploader(cfg), use_cache=True)
    apply_media_results(dataset, media_results)
    with SSHTunnel(cfg):
        writer = MySQLWriter(cfg)
        writer.connect()
        try:
            writer.preflight()
            written = write_dataset(dataset, writer)
        finally:
            writer.close()
    return {
        "ok": True,
        "sync": True,
        "counts": dataset.counts(),
        "media_uploaded_or_cached": len(media_results),
        "written": written,
        "warnings": dataset.warnings[:50],
    }


def preflight() -> dict[str, Any]:
    cfg = SyncConfig.from_env()
    missing = cfg.missing_for_mysql()
    if missing:
        return {"ok": False, "error": f"missing env: {', '.join(missing)}"}
    try:
        with SSHTunnel(cfg):
            writer = MySQLWriter(cfg)
            writer.connect()
            try:
                writer.preflight()
            finally:
                writer.close()
    except Exception as exc:
        return {"ok": False, "preflight": False, "error": str(exc)}
    return {"ok": True, "preflight": True}


def smoke_media(limit: int | None = 1) -> dict[str, Any]:
    cfg = SyncConfig.from_env()
    missing = cfg.missing_for_media()
    if missing:
        return {"ok": False, "error": f"missing env: {', '.join(missing)}"}
    dataset = build_current_dataset(limit=limit)
    media = next((item for item in dataset.media if item.file_path is not None), None)
    if media is None:
        return {"ok": False, "error": "no existing media file found"}
    result = MediaUploader(cfg).upload(media)
    return {"ok": True, "media": asdict(result)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--smoke-media", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    if args.dry_run:
        result = dry_run(limit=args.limit)
    elif args.fake:
        result = run_fake(limit=args.limit)
    elif args.smoke_media:
        result = smoke_media(limit=args.limit or 1)
    elif args.preflight:
        result = preflight()
    elif args.sync:
        result = run_sync(limit=args.limit)
    else:
        result = dry_run(limit=args.limit)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
