# OpenClaw Agent Contract

This project exposes a fixed image-processing pipeline for a travel-agency
internal LINE OA agent. OpenClaw should treat the pipeline as a tool, not as
conversation logic.

## Fixed Pipeline

RPA saves images into:

```text
line-rpa/download/<line-group-name>/
```

Raw images in the group folder are classified into:

```text
line-rpa/download/<line-group-name>/travel/
line-rpa/download/<line-group-name>/other/
line-rpa/download/<line-group-name>/review/
line-rpa/download/<line-group-name>/error/
```

`line-rpa/download/<line-group-name>/inbox/` remains supported only as a
compatibility input folder.

Then run:

```bash
python tools/pipeline/process_downloads.py --target "<line-group-name>" --json
```

When the LINE RPA is used for multiple groups, downloads are completed for all
selected groups first. After the download phase finishes, `ok` and `partial`
groups run this pipeline sequentially; `failed` groups skip the pipeline and
should be reported as download failures. This keeps LINE/window automation
separate from slower OCR and branding work.

The command reuses the current implementation:

1. `filter/filter.py` runs OCR and keeps only travel images.
2. Travel images are moved to `line-rpa/download/<line-group-name>/travel/`.
3. `tools/branding/brand_stitcher.py` stitches `config/brand.png`.
4. Branded images are written to `line-rpa/download/<line-group-name>/branded/`.
5. `tools/indexing/reindex.py` rebuilds `config/travel_index.db`.
6. The pipeline syncs `line-rpa/download/image_index.json` from classified original images in `travel/`, `other/`, and `review/` for each target. `branded/` is excluded because it contains derived logo-stitched images.
7. Pipeline JSON output includes `review_images`, grouped by target, listing files under `line-rpa/download/<target>/review/` that need user confirmation.

OpenClaw should query `config/travel_index.db` as the source of truth and
send `branded` images first.

## Useful Commands

Process every discovered downloads folder:

```bash
python tools/pipeline/process_downloads.py
```

Process one LINE group folder:

```bash
python tools/pipeline/process_downloads.py --target "<line-group-name>"
```

Preview planned commands:

```bash
python tools/pipeline/process_downloads.py --dry-run
```

Return machine-readable output:

```bash
python tools/pipeline/process_downloads.py --json
```

## OpenClaw Query Operations

OpenClaw can query itineraries by structured filters with:

```bash
python tools/openclaw/operations.py query --country "泰國" --month 7 --price-min 20000 --price-max 40000
```

Supported filters:

```text
--country   repeatable
--region    repeatable
--month     repeatable integer
--airline   repeatable
--feature   repeatable
--price-min
--price-max
--duration-days
--duration-min
--duration-max
--target
--limit
```

OpenClaw can query processed results with:

```bash
python tools/openclaw/operations.py latest --limit 10
```

Useful variants:

```bash
python tools/openclaw/operations.py latest --hours 24
python tools/openclaw/operations.py latest --target "<line-group-name>" --limit 10
```

This operation reads `config/travel_index.db` and returns JSON containing
`branded_path`, source group, parsed countries, regions, months, price,
duration, features, `source_time`, and `indexed_at`.

OpenClaw can find likely duplicate products with:

```bash
python tools/openclaw/operations.py duplicates
```

Duplicate v1 rule:

- country and month are required
- records are grouped by country, region, month, duration, and rounded price
- groups must contain more than one source by default
- no image is deleted or hidden

To record an employee review decision:

```bash
python tools/openclaw/operations.py review-duplicate --group-id "<group-id>" --keep "<sidecar-path>"
```

The review is saved to `config/duplicate_reviews.json`.

OpenClaw can summarize processing status with:

```bash
python tools/openclaw/operations.py status
python tools/openclaw/operations.py status --target "<line-group-name>"
```

This returns counts for inbox, travel, branded, other, error, indexed rows,
latest file time, and latest indexed time.

## Agent Rules

- Prefer this project (`LINE-downloader-main`) and its existing scripts for all RPA/image-processing work. Do not create alternate ad-hoc workflows unless explicitly requested.
- Treat RPA as a downloader only: it may open LINE, navigate groups, download images, and stop when exact downloaded-image hashes are encountered. It must not own OCR, branding, duplicate review, or outbound sending logic.
- For multi-group runs, download all selected groups first, then run each successful/partial group's pipeline sequentially. Do not parallelize RPA or pipeline work until explicit locking/queueing is designed.
- Do not implement OCR, branding, or indexing inside OpenClaw prompts. Trigger the fixed project scripts instead.
- Pipeline output `review_images` means user confirmation is required. Images in `review/` must be confirmed and moved to `travel/` or `other/` before cross-group duplicate checks.
- If review confirmation moves an image to `travel/`, run branding and reindex afterward; if it moves to `other/`, sync `image_index.json` afterward.
- Do not run cross-group branded duplicate checks until all successful group pipelines are complete and all review images are resolved.
- Cross-group duplicate checks should use existing OCR sidecars / `travel_index.db` data; do not OCR the same image again unless explicitly forced.
- `travel_index.db` is a rebuildable query index for currently usable branded results, not the only source of workflow state.
- `line-rpa/download/image_index.json` is the central per-group downloaded-image hash index. Sync it from `travel/`, `other/`, and `review/`; never from `branded/`.
- Duplicate candidates must not be deleted automatically. Present likely duplicates to the user and record/act only after confirmation.
- Query only processed data from `travel_index.db` for normal lookup operations.
- Before sending images externally, ask for confirmation with image numbers and target group.
- Use LINE Messaging API for final delivery after confirmation.
