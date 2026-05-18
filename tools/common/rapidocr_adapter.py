"""Compatibility helpers for RapidOCR package variants."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = PROJECT_ROOT / ".cache" / "rapidocr-models"


def load_rapidocr_class():
    """Return RapidOCR from either the legacy or current package."""
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
    """Normalize legacy tuple output and modern RapidOCROutput to text lines."""
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
