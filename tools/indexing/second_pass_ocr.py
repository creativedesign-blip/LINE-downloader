"""Second-pass OCR refresh and optional structured extraction for travel DM text.

Run it directly, or through process_downloads.py --second-pass-ocr, to refresh
only sidecars whose first-pass extraction looks ambiguous or incomplete.

Provider behavior:
- auto / paddle-ocr: refresh only suspicious sidecars with PaddleOCR.
- openai: explicit structured extraction provider for manual experiments.

OpenAI Structured Outputs is kept as an explicit provider only; it is not the
default fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.branding.io_utils import image_of_sidecar, save_sidecar
from tools.common.image_seen import file_sha256
from tools.common.targets import load_target_ids, relpath_from_root
from tools.indexing.extractor import (
    extract_country,
    extract_duration,
    extract_months,
    extract_price_from,
    extract_region,
)
from tools.indexing.paddle_ocr import create_paddle_ocr_engine
from tools.indexing.plan_extractor import extract_plans
from tools.indexing.ocr_enrich import enrich_one
from tools.indexing.reindex import collect_travel_sidecars

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_YEAR = 2026
MIN_PRICE = 5000
MAX_PRICE = 999999
SECOND_PASS_OCR_KEY = "secondPassOcr"
SECOND_PASS_PROVIDER = "paddle-ocr"
SECOND_PASS_ENGINE = "paddleocr"
REASON_PRIORITY = {
    "missing_duration": 0,
    "suspicious_duration": 1,
    "missing_price": 2,
    "split_duration_marker": 3,
    "missing_region": 4,
    "multi_plan_layout": 5,
}
SPLIT_DURATION_MARKER_RE = re.compile(
    r"(?:\d|[\u4e00\u4e8c\u5169\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341])"
    r"\s*\n\s*(?:\u5929|\u65e5|\u3089|\u3071)"
)


@dataclass(frozen=True)
class SecondPassProduct:
    title: str
    country: str
    regions: list[str]
    duration_days: Optional[int]
    price_from: Optional[int]
    departures: list[str]
    evidence: list[str]
    confidence: str


@dataclass(frozen=True)
class SecondPassResult:
    sidecar_path: str
    provider: str
    first_pass: dict[str, Any]
    products: list[SecondPassProduct]
    warnings: list[str]
    accepted: bool


@dataclass(frozen=True)
class OcrRefreshResult:
    sidecar_path: str
    provider: str
    status: str
    before: dict[str, Any]
    after: dict[str, Any]
    fallback_reason: Optional[str] = None


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ocr_text(sidecar: dict[str, Any]) -> str:
    ocr = sidecar.get("ocr") or {}
    return str(ocr.get("text") or "")


def load_sidecar(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def has_split_duration_marker(text: str) -> bool:
    return bool(SPLIT_DURATION_MARKER_RE.search(text))


def needs_second_pass(text: str) -> tuple[bool, list[str]]:
    """Return whether OCR text is worth sending to the second pass."""
    reasons: list[str] = []
    duration = extract_duration(text)
    price = extract_price_from(text)
    regions = extract_region(text)
    plans = extract_plans(text)
    plan_prices = [p.price_from for p in plans if p.price_from]

    if duration is None:
        reasons.append("missing_duration")
    elif duration > 15:
        reasons.append("suspicious_duration")
    if price is None and not plan_prices:
        reasons.append("missing_price")
    if not regions:
        reasons.append("missing_region")
    if len(plans) > 1:
        multi_price = len({p.price_from for p in plans if p.price_from}) > 1
        multi_departures = sum(len(p.departures) for p in plans) >= 4
        if multi_price or multi_departures:
            reasons.append("multi_plan_layout")
    if has_split_duration_marker(text):
        reasons.append("split_duration_marker")

    return bool(reasons), reasons


def candidate_priority(item: tuple[Path, list[str]]) -> tuple[int, int, str]:
    """Process the most useful second-pass candidates first."""
    path, reasons = item
    top_reason = min(
        (REASON_PRIORITY.get(reason, 99) for reason in reasons),
        default=99,
    )
    return (top_reason, -len(reasons), relpath_from_root(path))


def candidate_sidecars(paths: Iterable[Path]) -> list[tuple[Path, list[str]]]:
    out: list[tuple[Path, list[str]]] = []
    for path in paths:
        try:
            text = _ocr_text(load_sidecar(path))
        except (OSError, json.JSONDecodeError):
            continue
        ok, reasons = needs_second_pass(text)
        if ok:
            out.append((path, reasons))
    out.sort(key=candidate_priority)
    return out


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["products", "warnings"],
        "properties": {
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "title",
                        "country",
                        "regions",
                        "duration_days",
                        "price_from",
                        "departures",
                        "evidence",
                        "confidence",
                    ],
                    "properties": {
                        "title": {"type": "string"},
                        "country": {"type": "string"},
                        "regions": {"type": "array", "items": {"type": "string"}},
                        "duration_days": {"type": "integer", "minimum": 0, "maximum": 30},
                        "price_from": {"type": "integer", "minimum": 0, "maximum": MAX_PRICE},
                        "departures": {
                            "type": "array",
                            "items": {"type": "string", "pattern": r"^20\d{2}-\d{2}-\d{2}$"},
                        },
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                },
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
    }


def _prompt(text: str, first_pass: dict[str, Any]) -> str:
    return (
        "You are extracting Taiwan travel agency DM products from OCR text.\n"
        "Return only products grounded in the OCR text. Do not invent products, "
        "prices, regions, or departure dates.\n"
        "Rules:\n"
        "- duration_days is the trip length, not a departure day number.\n"
        "- Treat strings like 7/29 日期 or 08/20 日本 as departure dates, not 29-day or 20-day trips.\n"
        "- If unknown, use 0 for numeric fields and an empty string/list for text/list fields.\n"
        "- Use ISO dates with year 2026 when OCR gives month/day without a year.\n"
        "- Put exact OCR snippets that justify each product in evidence.\n\n"
        f"First pass: {json.dumps(first_pass, ensure_ascii=False)}\n\n"
        f"OCR text:\n{text}"
    )


def _first_pass_summary(text: str) -> dict[str, Any]:
    return {
        "countries": extract_country(text),
        "regions": extract_region(text),
        "months": extract_months(text),
        "duration_days": extract_duration(text),
        "price_from": extract_price_from(text),
        "plan_count": len(extract_plans(text)),
    }


def _summary_from_sidecar(path: Path) -> dict[str, Any]:
    text = _ocr_text(load_sidecar(path))
    return _first_pass_summary(text)


def _image_hash_for_sidecar(path: Path) -> Optional[str]:
    try:
        return file_sha256(image_of_sidecar(path))
    except OSError:
        return None


def _second_pass_cache_matches(sidecar: dict[str, Any], image_hash: Optional[str]) -> bool:
    block = sidecar.get(SECOND_PASS_OCR_KEY) or {}
    return bool(
        image_hash
        and isinstance(block, dict)
        and block.get("provider") == SECOND_PASS_PROVIDER
        and block.get("imageSha256") == image_hash
    )


def _write_second_pass_status(
    path: Path,
    *,
    image_hash: Optional[str],
    reasons: list[str],
    status: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    sidecar = load_sidecar(path)
    sidecar[SECOND_PASS_OCR_KEY] = {
        "provider": SECOND_PASS_PROVIDER,
        "engine": SECOND_PASS_ENGINE,
        "imageSha256": image_hash,
        "processedAt": _iso_now(),
        "reasons": reasons,
        "status": status,
        "before": before,
        "after": after,
    }
    save_sidecar(image_of_sidecar(path), sidecar)


def call_openai_structured(text: str, *, model: str, api_key: str) -> dict[str, Any]:
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": "Extract structured travel itinerary products from OCR text as JSON.",
            },
            {"role": "user", "content": _prompt(text, _first_pass_summary(text))},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "travel_dm_second_pass",
                "strict": True,
                "schema": _schema(),
            }
        },
    }
    req = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc

    text_output = payload.get("output_text")
    if not text_output:
        chunks: list[str] = []
        for item in payload.get("output") or []:
            for part in item.get("content") or []:
                if part.get("type") in {"output_text", "text"} and part.get("text"):
                    chunks.append(str(part["text"]))
        text_output = "".join(chunks)
    if not text_output:
        raise RuntimeError("OpenAI response did not include output text")
    return json.loads(text_output)


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_structured_output(raw: dict[str, Any], source_text: str) -> tuple[list[SecondPassProduct], list[str]]:
    products: list[SecondPassProduct] = []
    warnings: list[str] = []
    for index, item in enumerate(raw.get("products") or [], 1):
        if not isinstance(item, dict):
            warnings.append(f"product_{index}: not an object")
            continue

        title = str(item.get("title") or "").strip()
        country = str(item.get("country") or "").strip()
        regions = [str(v).strip() for v in item.get("regions") or [] if str(v).strip()]
        evidence = [str(v).strip() for v in item.get("evidence") or [] if str(v).strip()]
        departures = [str(v).strip() for v in item.get("departures") or [] if _valid_date(str(v).strip())]
        confidence = str(item.get("confidence") or "low")

        try:
            duration_days = int(item.get("duration_days") or 0)
        except (TypeError, ValueError):
            duration_days = 0
        if not 1 <= duration_days <= 30:
            duration_days = None

        try:
            price_from = int(item.get("price_from") or 0)
        except (TypeError, ValueError):
            price_from = 0
        if not MIN_PRICE <= price_from <= MAX_PRICE:
            price_from = None

        missing_evidence = [snippet for snippet in evidence if snippet and snippet not in source_text]
        if missing_evidence:
            warnings.append(f"product_{index}: evidence_not_in_ocr={missing_evidence[:3]}")
            continue
        if not any([title, regions, duration_days, price_from, departures]):
            warnings.append(f"product_{index}: empty product")
            continue

        products.append(
            SecondPassProduct(
                title=title,
                country=country,
                regions=regions,
                duration_days=duration_days,
                price_from=price_from,
                departures=departures,
                evidence=evidence,
                confidence=confidence if confidence in {"high", "medium", "low"} else "low",
            )
        )
    warnings.extend(str(w) for w in raw.get("warnings") or [] if str(w).strip())
    return products, warnings


def _call_provider(
    text: str,
    *,
    provider: str,
    openai_model: str,
) -> tuple[str, dict[str, Any]]:
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for provider=openai")
        return "openai", call_openai_structured(text, model=openai_model, api_key=api_key)
    raise ValueError(f"unknown provider: {provider}")


def extract_sidecar(
    path: Path,
    *,
    provider: str,
    openai_model: str,
) -> SecondPassResult:
    sidecar = load_sidecar(path)
    text = _ocr_text(sidecar)
    first_pass = _first_pass_summary(text)
    used_provider, raw = _call_provider(
        text,
        provider=provider,
        openai_model=openai_model,
    )
    products, warnings = validate_structured_output(raw, text)
    return SecondPassResult(
        sidecar_path=relpath_from_root(path),
        provider=used_provider,
        first_pass=first_pass,
        products=products,
        warnings=warnings,
        accepted=bool(products),
    )


def refresh_sidecar_with_paddle_ocr(
    engine: Any,
    path: Path,
    *,
    force: bool = False,
    reasons: Optional[list[str]] = None,
    fallback_reason: Optional[str] = None,
) -> OcrRefreshResult:
    reasons = reasons or []
    before = _summary_from_sidecar(path)
    image_hash = _image_hash_for_sidecar(path)
    sidecar = load_sidecar(path)
    if not force and _second_pass_cache_matches(sidecar, image_hash):
        return OcrRefreshResult(
            sidecar_path=relpath_from_root(path),
            provider=SECOND_PASS_PROVIDER,
            status="skipped_second_pass_cache",
            before=before,
            after=before,
            fallback_reason=fallback_reason,
        )

    status = enrich_one(
        engine,
        image_of_sidecar(path),
        force=True,
        engine_name=SECOND_PASS_ENGINE,
        include_price_ocr=False,
    )
    after = _summary_from_sidecar(path)
    _write_second_pass_status(
        path,
        image_hash=image_hash,
        reasons=reasons,
        status=status,
        before=before,
        after=after,
    )
    return OcrRefreshResult(
        sidecar_path=relpath_from_root(path),
        provider=SECOND_PASS_PROVIDER,
        status=status,
        before=before,
        after=after,
        fallback_reason=fallback_reason,
    )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Second-pass structured extraction for travel DM OCR.")
    parser.add_argument("sidecars", nargs="*", type=Path, help="specific sidecar JSON files to process")
    parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        help="scan one target id when sidecars are omitted; repeat for multiple targets",
    )
    parser.add_argument("--limit", type=int, default=10, help="maximum candidates to process; 0 or less processes all")
    parser.add_argument("--provider", choices=["auto", "paddle-ocr", "openai"], default="auto")
    parser.add_argument("--openai-model", default=os.environ.get("OPENAI_SECOND_PASS_MODEL", DEFAULT_OPENAI_MODEL))
    parser.add_argument(
        "--force-ocr",
        dest="force_ocr",
        action="store_true",
        help="force PaddleOCR refresh even when second-pass cache matches",
    )
    parser.add_argument(
        "--no-force-ocr",
        dest="force_ocr",
        action="store_false",
        help="skip sidecars already processed by second-pass OCR for the same image hash",
    )
    parser.set_defaults(force_ocr=False)
    parser.add_argument("--jsonl", action="store_true", help="stream one JSON result per line")
    parser.add_argument("--candidates-only", action="store_true", help="list candidate sidecars without calling a second-pass provider")
    return parser.parse_args(argv)


def _print_result(result: SecondPassResult | OcrRefreshResult, *, jsonl: bool) -> None:
    if jsonl:
        print(json.dumps(asdict(result), ensure_ascii=False), flush=True)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    paths = args.sidecars
    if not paths:
        target_ids = args.targets if args.targets else load_target_ids()
        paths = collect_travel_sidecars(target_ids)

    candidates = candidate_sidecars(paths)
    if int(args.limit) > 0:
        candidates = candidates[: int(args.limit)]

    if args.candidates_only:
        print(json.dumps(
            [
                {"sidecar_path": relpath_from_root(path), "reasons": reasons}
                for path, reasons in candidates
            ],
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    resolved_provider = args.provider
    if args.provider == "auto":
        resolved_provider = "paddle-ocr"

    if resolved_provider == "paddle-ocr":
        results = []
        engine = None
        for index, (path, _reasons) in enumerate(candidates, 1):
            print(f"[second-pass] {index}/{len(candidates)} {relpath_from_root(path)}", file=sys.stderr, flush=True)
            if not args.force_ocr:
                image_hash = _image_hash_for_sidecar(path)
                sidecar = load_sidecar(path)
                if _second_pass_cache_matches(sidecar, image_hash):
                    before = _summary_from_sidecar(path)
                    result = OcrRefreshResult(
                        sidecar_path=relpath_from_root(path),
                        provider=SECOND_PASS_PROVIDER,
                        status="skipped_second_pass_cache",
                        before=before,
                        after=before,
                    )
                    results.append(result)
                    _print_result(result, jsonl=args.jsonl)
                    continue
            if engine is None:
                try:
                    engine = create_paddle_ocr_engine()
                except ImportError as exc:
                    raise SystemExit(f"paddleocr is required for provider=paddle-ocr: {exc}") from exc
            result = refresh_sidecar_with_paddle_ocr(engine, path, force=args.force_ocr, reasons=_reasons)
            results.append(result)
            _print_result(result, jsonl=args.jsonl)
        if args.jsonl:
            return 0
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
        return 0

    results = []
    for index, (path, _reasons) in enumerate(candidates, 1):
        print(f"[second-pass] {index}/{len(candidates)} {relpath_from_root(path)}", file=sys.stderr, flush=True)
        result = extract_sidecar(
            path,
            provider=resolved_provider,
            openai_model=args.openai_model,
        )
        results.append(result)
        _print_result(result, jsonl=args.jsonl)
    if args.jsonl:
        return 0
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
