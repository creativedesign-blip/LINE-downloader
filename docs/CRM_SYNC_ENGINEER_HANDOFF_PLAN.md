# CRM Sync Engineer Handoff Plan

## 1. Decision Summary

The CRM system does not need to connect to the local SQLite files directly. The local desktop app remains the source of truth, and a sync job will push a read-optimized mirror into the CRM team's MySQL database.

Direction:

- One-way sync: local SQLite -> CRM MySQL.
- CRM treats synced tables as read-only.
- CRM chatbot queries MySQL directly with SELECT.
- Local SQLite schemas should not be modified for this integration.
- CRM MySQL tables can be created from the schema below.

Primary local sources:

- `data/travel_index.db`
  - `itineraries`
  - `itinerary_plans`
  - `itinerary_departures`
- `logs/openclaw/upload_catalog.db`
  - `upload_folders`
  - `uploaded_images`
  - `manual_tags`
  - `uploaded_image_search_index`

## 2. CRM MySQL Tables

The CRM engineer should create these tables first. These are the chatbot-facing read model tables, not a 1:1 copy of every local SQLite table.

### `crm_assets`

Stores image assets and public image links.

```sql
CREATE TABLE crm_assets (
  asset_id             VARCHAR(512) NOT NULL,
  source_table         VARCHAR(64) NOT NULL,
  source_pk            VARCHAR(512) NOT NULL,
  source_kind          VARCHAR(64),
  image_path           TEXT,
  branded_path         TEXT,
  public_image_url     TEXT,
  image_sha256         VARCHAR(64),
  image_phash          VARCHAR(64),
  status               VARCHAR(64) DEFAULT 'active',
  source_time          VARCHAR(32),
  indexed_at           VARCHAR(32),
  updated_at           VARCHAR(32),
  PRIMARY KEY (asset_id),
  UNIQUE KEY uq_asset_source (source_table, source_pk),
  KEY idx_asset_sha256 (image_sha256),
  KEY idx_asset_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### `crm_itineraries`

Main chatbot search table for trips.

```sql
CREATE TABLE crm_itineraries (
  itinerary_id         VARCHAR(512) NOT NULL,
  asset_id             VARCHAR(512),
  source_table         VARCHAR(64) NOT NULL,
  source_pk            VARCHAR(512) NOT NULL,
  product_title        VARCHAR(512),
  group_name           VARCHAR(512),
  country_csv          VARCHAR(255),
  region_csv           VARCHAR(512),
  destination_text     TEXT,
  features_csv         TEXT,
  months_csv           VARCHAR(128),
  price_from_twd       INT,
  duration_days        INT,
  raw_text             MEDIUMTEXT,
  public_image_url     TEXT,
  branded_path         TEXT,
  indexed_at           VARCHAR(32),
  updated_at           VARCHAR(32),
  PRIMARY KEY (itinerary_id),
  UNIQUE KEY uq_itinerary_source (source_table, source_pk),
  KEY idx_itin_asset (asset_id),
  KEY idx_itin_price (price_from_twd),
  KEY idx_itin_duration (duration_days),
  KEY idx_itin_indexed (indexed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### `crm_departures`

Date-specific table for questions like "8/23 有沒有團".

```sql
CREATE TABLE crm_departures (
  departure_id         VARCHAR(512) NOT NULL,
  itinerary_id         VARCHAR(512),
  asset_id             VARCHAR(512),
  departure_date       DATE,
  date_text            VARCHAR(128),
  month                TINYINT,
  day                  TINYINT,
  weekday              TINYINT,
  price_from_twd       INT,
  duration_days        INT,
  public_image_url     TEXT,
  indexed_at           VARCHAR(32),
  PRIMARY KEY (departure_id),
  KEY idx_dep_date (departure_date),
  KEY idx_dep_month_day (month, day),
  KEY idx_dep_itinerary (itinerary_id),
  KEY idx_dep_price (price_from_twd),
  KEY idx_dep_duration (duration_days)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### `crm_search_tokens`

Search helper table. A token is a normalized searchable value extracted from country, region, title, OCR text, features, months, duration, and price.

Example: one itinerary containing "北海道5天 函館 小樽 46800起 8月出發" becomes multiple rows:

- `region / 北海道 / 北海道`
- `city / 函館 / 函館`
- `city / 小樽 / 小樽`
- `duration / 5天 / 5`
- `month / 8月 / 8`
- `price / 46800起 / 46800`

```sql
CREATE TABLE crm_search_tokens (
  token_id             BIGINT NOT NULL AUTO_INCREMENT,
  itinerary_id         VARCHAR(512),
  asset_id             VARCHAR(512),
  token_type           VARCHAR(64) NOT NULL,
  token_value          VARCHAR(255) NOT NULL,
  normalized_token     VARCHAR(255) NOT NULL,
  source_field         VARCHAR(64),
  confidence           DECIMAL(5,4) DEFAULT 1.0000,
  weight               INT DEFAULT 1,
  PRIMARY KEY (token_id),
  UNIQUE KEY uq_token (
    itinerary_id,
    asset_id,
    token_type,
    normalized_token,
    source_field
  ),
  KEY idx_token_norm (normalized_token),
  KEY idx_token_type_norm (token_type, normalized_token),
  KEY idx_token_itinerary (itinerary_id),
  KEY idx_token_asset (asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### `crm_sync_status`

Used by the sync job to report freshness and errors.

```sql
CREATE TABLE crm_sync_status (
  id                   TINYINT NOT NULL PRIMARY KEY,
  last_run_at          VARCHAR(32),
  last_success_at      VARCHAR(32),
  last_error           TEXT,
  last_error_at        VARCHAR(32),
  last_counts_json     JSON
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### Optional `crm_query_logs`

This can also live in the chatbot team's own DB. It should not be treated as sync-owned data.

```sql
CREATE TABLE crm_query_logs (
  id                   BIGINT NOT NULL AUTO_INCREMENT,
  user_question        TEXT NOT NULL,
  parsed_month         TINYINT,
  parsed_departure_date DATE,
  parsed_duration_days INT,
  parsed_budget_twd    INT,
  parsed_keywords_json JSON,
  matched_count        INT DEFAULT 0,
  fallback_level       VARCHAR(64),
  response_summary     TEXT,
  created_at           VARCHAR(32) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_query_created (created_at),
  KEY idx_query_month (parsed_month),
  KEY idx_query_budget (parsed_budget_twd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 3. Field Mapping

### Local `itineraries` -> `crm_assets`

| CRM field | Local source |
|---|---|
| `asset_id` | `itineraries.sidecar_path` |
| `source_table` | literal `itineraries` |
| `source_pk` | `itineraries.sidecar_path` |
| `source_kind` | literal `travel_index` |
| `image_path` | `itineraries.image_path` |
| `branded_path` | `itineraries.branded_path` |
| `public_image_url` | generated from `branded_path` |
| `image_sha256` | `itineraries.image_sha256` |
| `image_phash` | `itineraries.image_phash` |
| `status` | `active` when `branded_path` exists, otherwise `needs_review` |
| `source_time` | `itineraries.source_time` |
| `indexed_at` | `itineraries.indexed_at` |

### Local `itinerary_plans` -> `crm_itineraries`

| CRM field | Local source |
|---|---|
| `itinerary_id` | `itinerary_plans.plan_id` |
| `asset_id` | `itinerary_plans.sidecar_path` |
| `source_table` | literal `itinerary_plans` |
| `source_pk` | `itinerary_plans.plan_id` |
| `product_title` | `itinerary_plans.title` |
| `group_name` | `itinerary_plans.group_name` |
| `country_csv` | `itinerary_plans.country_csv` |
| `region_csv` | `itinerary_plans.region_csv` |
| `destination_text` | derived from `country_csv + region_csv + title` |
| `features_csv` | `itinerary_plans.features_csv` |
| `months_csv` | `itinerary_plans.months_csv` |
| `price_from_twd` | `itinerary_plans.price_from` |
| `duration_days` | `itinerary_plans.duration_days` |
| `raw_text` | `itinerary_plans.raw_text` |
| `public_image_url` | generated from `branded_path` |
| `branded_path` | `itinerary_plans.branded_path` |
| `indexed_at` | `itinerary_plans.indexed_at` |

### Local `itinerary_departures` -> `crm_departures`

| CRM field | Local source |
|---|---|
| `departure_id` | `itinerary_departures.departure_id` |
| `itinerary_id` | `itinerary_departures.plan_id` |
| `asset_id` | `itinerary_departures.sidecar_path` |
| `departure_date` | `itinerary_departures.departure_date` |
| `date_text` | `itinerary_departures.date_text` |
| `month` | `itinerary_departures.month` |
| `day` | `itinerary_departures.day` |
| `weekday` | `itinerary_departures.weekday` |
| `price_from_twd` | `itinerary_departures.price_from` |
| `duration_days` | `itinerary_departures.duration_days` |
| `public_image_url` | generated from `branded_path` |
| `indexed_at` | `itinerary_departures.indexed_at` |

## 4. CRM Media Upload Strategy

Local paths cannot be returned directly to LINE users. The sync uploads the
actual image file to the CRM media API and stores the CRM-returned public URL.

Endpoint:

```text
POST https://ddvpoc.star-bit.io/api/v1/media/upload
```

Multipart fields:

- `file`: image file body.
- `external_id`: CRM `asset_id`.
- `sha256`: SHA-256 of the exact file being uploaded.
- `source_kind`: `travel_index` or `upload_catalog`.
- `source_path`: local source path (`branded_path`, `image_path`, or `stored_path`).

Successful response:

```json
{
  "code": 200,
  "message": "上傳成功",
  "data": {
    "media_id": "<sha256>.jpg",
    "url": "https://ddvpoc.star-bit.io/uploads/<sha256>.jpg",
    "sha256": "<64hex>",
    "size": 12345,
    "deduplicated": false,
    "external_id": "...",
    "source_kind": "travel_index"
  }
}
```

Mapping:

- `data.media_id` -> `crm_media_id`.
- `data.url` -> `crm_media_url` and `public_image_url`.
- `data.deduplicated=true` is still success.
- MySQL stores metadata and URLs only; it does not store image BLOBs.

## 5. Sync Mechanism

Use snapshot reconciliation:

1. Read all mapped source rows from local SQLite in read-only mode.
2. Transform them into CRM rows.
3. Generate tokens.
4. Hash each transformed row.
5. Compare with local sync shadow state.
6. UPSERT new/changed rows into CRM MySQL.
7. DELETE rows that disappeared locally.
8. Update sync status and shadow only after successful MySQL writes.

Properties:

- Idempotent: safe to rerun.
- One-way: CRM does not write back.
- Non-fatal: failed sync should not break RPA or uploads.
- Near-real-time: run after pipeline completion and also on a periodic timer.

## 6. Token Generation Rules

Generate tokens from:

- `country_csv` -> `country`
- `region_csv` -> `region` or `city`
- `features_csv` -> `feature`
- `months_csv` -> `month`
- `duration_days` -> `duration`
- `price_from_twd` -> `price`
- `product_title`, `group_name`, `raw_text` -> `raw_ocr_keyword`

Normalization examples:

| Input | token_type | normalized_token |
|---|---|---|
| `8/23` | `date` | `08-23` |
| `8月`, `八月`, `08` | `month` | `8` |
| `5天4夜`, `五天四夜`, `5D4N` | `duration` | `5` |
| `5萬`, `五萬`, `50000`, `NT$50,000` | `price` | `50000` |
| `日本`, `Japan` | `country` | `日本` |
| `JP` | `country` | `日本` only if the synonym dictionary explicitly maps it |

## 7. Query Fallback Rules

The chatbot should query in stages. It should keep the user's most important intent visible in the reply when it relaxes filters.

Recommended fallback order:

1. Exact filters.
2. If date-specific query has no result, relax exact date to month.
3. If budget has no result, relax price by +20%, then +50%.
4. If duration has no result, relax to `duration_days ± 1`, then `± 2`.
5. If keywords have no result, keep primary destination and drop secondary feature words.
6. If still no result, return closest matches by destination/month and explain what was relaxed.

Example for "土耳其熱氣球 10 天 4 萬左右":

1. `土耳其 + 熱氣球 + duration_days = 10 + price <= 40000`
2. `土耳其 + 熱氣球 + duration_days BETWEEN 9 AND 11 + price <= 40000`
3. `土耳其 + 熱氣球 + duration_days BETWEEN 8 AND 12 + price <= 60000`
4. `土耳其 + 熱氣球` ordered by closest duration and lowest price
5. Reply: no exact 10-day 40k match; show closest options and say why.

## 8. CRM Engineer Handoff Message

You can tell the CRM engineer:

> We will not ask your CRM to connect to our desktop SQLite files. We will push a one-way read-only mirror into your MySQL database. Your chatbot should query the MySQL tables only.
>
> Please create the tables `crm_assets`, `crm_itineraries`, `crm_departures`, `crm_search_tokens`, and `crm_sync_status` using the DDL we provide. Optional chatbot-owned logs can go into `crm_query_logs`.
>
> We will sync travel rows, departure rows, searchable tokens, and public image URLs. You should treat all synced tables as read-only. If your chatbot needs conversation logs or customer notes, create separate CRM-owned tables.
>
> For chatbot search, use `crm_itineraries` for normal trip recommendations, `crm_departures` for date-specific questions, and `crm_search_tokens` for keyword matching such as destination, city, theme, duration, month, and price.
>
> The image field to return to LINE users is `public_image_url`. Do not use local file paths directly.

## 9. Next Execution Plan

1. Confirm public image URL base path and whether the current web app can serve `/media/...`.
2. Finalize the CRM DDL with the CRM engineer.
3. Implement the sync package in this repo.
4. Implement URL generation and token generation.
5. Add dry-run mode to show transformed rows and counts before writing to CRM.
6. Run a local dry run against SQLite only.
7. Smoke-test one CRM media upload.
8. Connect to CRM MySQL and perform a small limited sync.
9. Perform first full backfill after verification.
