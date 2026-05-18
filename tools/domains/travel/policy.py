"""Travel first-pass summary and second-pass candidate rules."""

from __future__ import annotations

import re
from typing import Any

from tools.domains.travel.constants import DOMAIN_NAME, SIDECAR_SCHEMA_VERSION
from tools.indexing.extractor import (
    extract_country,
    extract_duration,
    extract_months,
    extract_price_from,
    extract_region,
)
from tools.indexing.plan_extractor import extract_plans

REASON_PRIORITY = {
    "suspicious_duration": 0,
    "split_duration_marker": 1,
    "multi_plan_layout": 2,
    "missing_duration": 3,
    "missing_price": 4,
    "missing_region": 5,
}
SPLIT_DURATION_MARKER_RE = re.compile(
    r"(?:\d|[\u4e00\u4e8c\u5169\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341])"
    r"\s*\n\s*(?:\u5929|\u65e5|\u3089|\u3071)"
)
ITINERARY_HINT_RE = re.compile(
    r"(?:"
    r"itinerary|tour|package|departure|"
    r"\u884c\u7a0b|\u51fa\u767c|\u51fa\u5718|\u65c5\u904a|\u65c5\u884c|"
    r"\u81ea\u7531\u884c|\u5718\u9ad4|\u5718\u8cbb|\u5831\u540d|"
    r"\u65e5\u904a|\u5929\u6578"
    r")",
    re.IGNORECASE,
)
PRICE_HINT_RE = re.compile(
    r"(?:"
    r"NT\$|\$|TWD|USD|JPY|"
    r"\d[\d,]{3,}\s*(?:\u5143|\u8d77)|"
    r"\u552e\u50f9|\u5718\u8cbb|\u8cbb\u7528|\u50f9\u683c|\u6bcf\u4eba|"
    r"\u512a\u60e0|\u7279\u50f9|\u5831\u50f9|\u8d77\u50f9|\u672a\u7a05|\u542b\u7a05"
    r")",
    re.IGNORECASE,
)
STRONG_SECOND_PASS_REASONS = {
    "suspicious_duration",
    "split_duration_marker",
    "multi_plan_layout",
}
CONDITIONAL_MISSING_REASONS = {
    "missing_duration",
    "missing_price",
    "missing_region",
}


def has_split_duration_marker(text: str) -> bool:
    return bool(SPLIT_DURATION_MARKER_RE.search(text))


def first_pass_summary(text: str) -> dict[str, Any]:
    return {
        "countries": extract_country(text),
        "regions": extract_region(text),
        "months": extract_months(text),
        "duration_days": extract_duration(text),
        "price_from": extract_price_from(text),
        "plan_count": len(extract_plans(text)),
    }


def second_pass_reasons(text: str) -> list[str]:
    """Return stable reasons for sending OCR text to a second pass."""
    reasons: list[str] = []
    summary = first_pass_summary(text)
    duration = summary["duration_days"]
    price = summary["price_from"]
    regions = summary["regions"]
    countries = summary["countries"]
    months = summary["months"]
    plans = extract_plans(text)
    plan_prices = [p.price_from for p in plans if p.price_from]
    has_price = price is not None or bool(plan_prices)
    has_price_hint = bool(PRICE_HINT_RE.search(text))
    split_duration = has_split_duration_marker(text)
    multi_plan_layout = False

    if duration is not None and duration > 15:
        reasons.append("suspicious_duration")

    if len(plans) > 1:
        multi_price = len({p.price_from for p in plans if p.price_from}) > 1
        multi_departures = sum(len(p.departures) for p in plans) >= 4
        if multi_price or multi_departures:
            multi_plan_layout = True
            reasons.append("multi_plan_layout")

    if split_duration:
        reasons.append("split_duration_marker")

    if duration is None and (multi_plan_layout or split_duration or ITINERARY_HINT_RE.search(text)):
        reasons.append("missing_duration")

    if not has_price and has_price_hint:
        reasons.append("missing_price")

    region_context_score = sum([bool(countries), bool(months), has_price or has_price_hint])
    if not regions and region_context_score >= 2:
        reasons.append("missing_region")

    has_strong_reason = any(reason in STRONG_SECOND_PASS_REASONS for reason in reasons)
    missing_reason_count = sum(reason in CONDITIONAL_MISSING_REASONS for reason in reasons)
    if not has_strong_reason and missing_reason_count < 2:
        return []

    return reasons


def second_pass_candidate(text: str) -> dict[str, Any]:
    reasons = second_pass_reasons(text)
    return {
        "needed": bool(reasons),
        "reasons": reasons,
    }


def apply_sidecar_metadata(sidecar: dict[str, Any], text: str) -> dict[str, Any]:
    """Return a copy with travel domain metadata derived from OCR text."""
    updated = dict(sidecar)
    updated["domain"] = DOMAIN_NAME
    updated["schemaVersion"] = SIDECAR_SCHEMA_VERSION
    updated["firstPassSummary"] = first_pass_summary(text)
    updated["secondPassCandidate"] = second_pass_candidate(text)
    return updated
