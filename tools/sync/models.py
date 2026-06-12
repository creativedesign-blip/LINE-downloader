from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


Row = dict[str, Any]


@dataclass(frozen=True)
class MediaResult:
    media_id: str
    url: str
    sha256: str
    size: int | None = None
    deduplicated: bool = False
    raw: Row | None = None


@dataclass(frozen=True)
class AssetMedia:
    asset_id: str
    source_kind: str
    source_path: str
    file_path: Path | None
    sha256: str | None = None


@dataclass
class SyncDataset:
    assets: list[Row]
    itineraries: list[Row]
    departures: list[Row]
    search_tokens: list[Row]
    upload_folders: list[Row]
    manual_tags: list[Row]
    media: list[AssetMedia]
    warnings: list[str]

    def counts(self) -> Row:
        return {
            "crm_assets": len(self.assets),
            "crm_itineraries": len(self.itineraries),
            "crm_departures": len(self.departures),
            "crm_search_tokens": len(self.search_tokens),
            "crm_upload_folders": len(self.upload_folders),
            "crm_manual_tags": len(self.manual_tags),
            "media_candidates": len(self.media),
            "warnings": len(self.warnings),
        }
