"""Normalize travel sidecars into indexable document fields."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional

from tools.indexing.extractor import (
    extract_airline,
    extract_country,
    extract_duration,
    extract_features,
    extract_months,
    extract_price_from,
    extract_region,
)


def valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def second_pass_products(sidecar: dict[str, Any]) -> list[dict[str, Any]]:
    block = sidecar.get("secondPassOcr") or {}
    if not isinstance(block, dict):
        return []
    if block.get("provider") != "codex" or block.get("status") != "enriched":
        return []
    products = block.get("products") or []
    return [item for item in products if isinstance(item, dict)]


def int_or_none(value: object, *, min_value: int, max_value: int) -> Optional[int]:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    if min_value <= parsed <= max_value:
        return parsed
    return None


def months_from_departures(departures: Iterable[str]) -> list[int]:
    months: set[int] = set()
    for departure in departures:
        if valid_iso_date(departure):
            months.add(int(departure[5:7]))
    return sorted(months)


def build_index_document(sidecar: dict[str, Any], text: str) -> dict[str, Any]:
    """Normalize one travel sidecar into aggregate fields used by DB rows."""
    countries = extract_country(text)
    months = extract_months(text)
    price_from = extract_price_from(text)
    airlines = extract_airline(text)
    regions = extract_region(text)
    duration_days = extract_duration(text)
    features = extract_features(text)
    products = second_pass_products(sidecar)

    if products:
        product_countries = [str(p.get("country") or "").strip() for p in products]
        product_regions = [
            str(region).strip()
            for p in products
            for region in (p.get("regions") or [])
            if str(region).strip()
        ]
        product_departures = [
            str(departure).strip()
            for p in products
            for departure in (p.get("departures") or [])
            if valid_iso_date(str(departure).strip())
        ]
        product_prices = [
            price for price in (
                int_or_none(p.get("price_from"), min_value=5000, max_value=999999)
                for p in products
            )
            if price is not None
        ]
        product_durations = [
            days for days in (
                int_or_none(p.get("duration_days"), min_value=1, max_value=30)
                for p in products
            )
            if days is not None
        ]
        countries = sorted(set(countries) | {country for country in product_countries if country})
        regions = sorted(set(regions) | set(product_regions))
        months = sorted(set(months) | set(months_from_departures(product_departures)))
        if product_prices:
            price_from = min([value for value in [price_from, *product_prices] if value is not None])
        if duration_days is None and product_durations:
            duration_days = min(product_durations)

    return {
        "countries": countries,
        "months": months,
        "price_from": price_from,
        "airlines": airlines,
        "regions": regions,
        "duration_days": duration_days,
        "features": features,
        "second_pass_products": products,
    }
