"""Heuristic plan/departure extraction from OCR text.

This module complements the image-level index.  It tries to split one image into
multiple purchasable plans when the DM contains repeated price/date blocks, then
normalizes each departure date into one row so queries can ask things like
"韓國最早週六出發" without mixing plan A/B/C dates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from tools.indexing.extractor import (
    extract_airline,
    extract_country,
    extract_duration,
    extract_features,
    extract_months,
    extract_price_from,
    extract_region,
    normalize_price_digits,
)

DEFAULT_YEAR = 2026

_PRICE_RE = re.compile(
    r"(?:NT\$|\$)?\s*(\d{1,3}(?:[,，.]\d{3})|\d{4,6})\s*(?:元|含稅|含税|起)?"
)
_MONTH_DAY_LIST_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})((?:\s*[.,、，]\s*\d{1,2})*)"
)
_FULL_DATE_RE = re.compile(r"(20\d{2})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{1,2})")
_DATE_LINE_RE = re.compile(r"\d{1,2}\s*/\s*\d{1,2}|20\d{2}\s*/\s*\d{1,2}\s*/\s*\d{1,2}")
_PRICE_LINE_RE = re.compile(r"(?:NT\$|\$)?\s*\d{1,3}(?:[,，.]\d{3})|\d{4,6}\s*(?:元|含稅|含税|起)")


@dataclass(frozen=True)
class Departure:
    date_text: str
    date_iso: str
    month: int
    day: int
    weekday: int  # ISO weekday: Mon=1 ... Sun=7


@dataclass(frozen=True)
class Plan:
    plan_no: int
    title: str
    raw_text: str
    countries: list[str]
    regions: list[str]
    airlines: list[str]
    features: list[str]
    months: list[int]
    price_from: Optional[int]
    duration_days: Optional[int]
    departures: list[Departure]


def _clean_price(raw: str) -> Optional[int]:
    value = normalize_price_digits(raw)
    if value is None:
        return None
    if 1000 <= value <= 99_999_999:
        return value
    return None


def _parse_departures(text: str, default_year: int = DEFAULT_YEAR) -> list[Departure]:
    found: dict[str, Departure] = {}

    def add(year: int, month: int, day: int, source: str) -> None:
        try:
            dt = date(year, month, day)
        except ValueError:
            return
        iso = dt.isoformat()
        found[iso] = Departure(
            date_text=source,
            date_iso=iso,
            month=month,
            day=day,
            weekday=dt.isoweekday(),
        )

    for m in _FULL_DATE_RE.finditer(text):
        y, mo, d = (int(m.group(i)) for i in (1, 2, 3))
        add(y, mo, d, m.group(0))

    # Handles 7/11.18.25, 07/12,08/23.31, 6/3、6/5, etc.
    for m in _MONTH_DAY_LIST_RE.finditer(text):
        mo = int(m.group(1))
        first_day = int(m.group(2))
        tail_days = [int(x) for x in re.findall(r"\d{1,2}", m.group(3) or "")]
        for d in [first_day] + tail_days:
            add(default_year, mo, d, m.group(0))

    return sorted(found.values(), key=lambda d: d.date_iso)


def _price_matches(text: str) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for m in _PRICE_RE.finditer(text):
        price = _clean_price(m.group(0))
        if price is None:
            continue
        # Filter likely flight numbers/times; true travel prices in this corpus
        # are mostly 5 digits and above, but keep low valid values for tests.
        if price < 3000:
            continue
        out.append((m.start(), m.end(), price))
    return out


def _title_from_block(block: str) -> str:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    keep: list[str] = []
    for ln in lines:
        if _DATE_LINE_RE.search(ln) or _PRICE_LINE_RE.search(ln):
            continue
        if any(token in ln for token in ("出發", "日期", "含稅", "含税", "起")) and len(ln) < 12:
            continue
        keep.append(ln)
        if len(" / ".join(keep)) >= 80 or len(keep) >= 4:
            break
    title = " / ".join(keep).strip()
    return title[:160]


def _plan_from_block(plan_no: int, block: str, price: Optional[int], *, default_year: int) -> Plan:
    departures = _parse_departures(block, default_year=default_year)
    months = sorted({d.month for d in departures}) or extract_months(block)
    return Plan(
        plan_no=plan_no,
        title=_title_from_block(block),
        raw_text=block.strip(),
        countries=extract_country(block),
        regions=extract_region(block),
        airlines=extract_airline(block),
        features=extract_features(block),
        months=months,
        price_from=price if price is not None else extract_price_from(block),
        duration_days=extract_duration(block),
        departures=departures,
    )


def extract_plans(text: str, *, default_year: int = DEFAULT_YEAR) -> list[Plan]:
    """Extract one or more plan records from OCR text.

    Heuristic: repeated price blocks usually correspond to repeated plan cards.
    We create one plan per price occurrence and use the surrounding text region;
    if a block has no date due to OCR layout, we borrow nearby dates.  If no
    price is found, return a single image-level plan with all dates.
    """
    text = text or ""
    if not text.strip():
        return []

    prices = _price_matches(text)
    if not prices:
        return [_plan_from_block(1, text, None, default_year=default_year)]

    plans: list[Plan] = []
    for idx, (start, end, price) in enumerate(prices, 1):
        prev_end = prices[idx - 2][1] if idx > 1 else 0
        next_start = prices[idx][0] if idx < len(prices) else len(text)
        # Keep blocks between neighbouring prices so plan A/B/C dates do not
        # bleed into each other. If this strict block has no dates, we fall back
        # to a nearby window below.
        block_start = prev_end
        block_end = next_start
        block = text[block_start:block_end]
        plan = _plan_from_block(idx, block, price, default_year=default_year)
        if not plan.departures:
            nearby = text[max(0, start - 320):min(len(text), end + 320)]
            plan = _plan_from_block(idx, nearby, price, default_year=default_year)
        plans.append(plan)

    # Drop exact duplicate price/date/title plans produced by OCR repeated price
    # strings, but keep same price with different departures.
    unique: list[Plan] = []
    seen: set[tuple] = set()
    for plan in plans:
        key = (
            plan.price_from,
            tuple(d.date_iso for d in plan.departures),
            plan.title[:40],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(Plan(
            plan_no=len(unique) + 1,
            title=plan.title,
            raw_text=plan.raw_text,
            countries=plan.countries,
            regions=plan.regions,
            airlines=plan.airlines,
            features=plan.features,
            months=plan.months,
            price_from=plan.price_from,
            duration_days=plan.duration_days,
            departures=plan.departures,
        ))
    return unique
