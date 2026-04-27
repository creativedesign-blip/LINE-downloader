"""Travel itinerary indexing: extract structured fields from OCR text and
store in SQLite for fast query by country / months / price / airline /
region / duration / features.
"""

from tools.indexing.extractor import (
    extract_airline,
    extract_country,
    extract_duration,
    extract_features,
    extract_months,
    extract_price_from,
    extract_region,
)
from tools.indexing.index_db import TravelIndex

__all__ = [
    "extract_airline",
    "extract_country",
    "extract_duration",
    "extract_features",
    "extract_months",
    "extract_price_from",
    "extract_region",
    "TravelIndex",
]
