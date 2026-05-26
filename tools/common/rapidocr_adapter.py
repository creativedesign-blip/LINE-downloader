"""Compatibility helpers for RapidOCR package variants."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = PROJECT_ROOT / ".cache" / "rapidocr-models"


def load_rapidocr_class():
    """Return RapidOCR from either the classic or current package."""
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        return RapidOCR
    except ImportError:
        from rapidocr import RapidOCR  # type: ignore

        return RapidOCR


def create_rapidocr():
    """Create RapidOCR with a writable model cache for modern rapidocr."""
    RapidOCR = load_rapidocr_class()
    if RapidOCR.__module__.startswith("rapidocr_onnxruntime"):
        return RapidOCR()

    model_dir = Path(os.environ.get("RAPIDOCR_MODEL_DIR") or DEFAULT_MODEL_DIR)
    model_dir.mkdir(parents=True, exist_ok=True)
    return RapidOCR(params={"Global.model_root_dir": str(model_dir)})


def rapidocr_lines(output: Any) -> list[str]:
    """Normalize tuple output and modern RapidOCROutput to text lines."""
    if output is None:
        return []

    result = output
    if isinstance(output, tuple):
        result = output[0] if output else None

    txts = getattr(result, "txts", None)
    if txts is not None:
        return [str(text) for text in txts if text]

    if not result:
        return []

    lines: list[str] = []
    for item in result:
        if len(item) >= 2 and item[1]:
            lines.append(str(item[1]))
    return lines


def rapidocr_with_boxes(output: Any) -> list[tuple[list, str, float]]:
    """Normalize output to list of (box, text, confidence) tuples.

    box is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] (four corners).
    """
    if output is None:
        return []

    result = output
    if isinstance(output, tuple):
        result = output[0] if output else None

    # Modern RapidOCROutput exposes .boxes / .txts / .scores attributes.
    boxes_attr = getattr(result, "boxes", None)
    txts_attr = getattr(result, "txts", None)
    if txts_attr is not None and boxes_attr is not None:
        scores_attr = getattr(result, "scores", None) or []
        items: list[tuple[list, str, float]] = []
        for i, text in enumerate(txts_attr):
            if not text:
                continue
            box = list(boxes_attr[i]) if i < len(boxes_attr) else []
            conf = float(scores_attr[i]) if i < len(scores_attr) else 0.0
            items.append((box, str(text), conf))
        return items

    if not result:
        return []

    items = []
    for item in result:
        if len(item) >= 2 and item[1]:
            box = item[0]
            text = str(item[1])
            conf = float(item[2]) if len(item) >= 3 else 0.0
            items.append((box, text, conf))
    return items
