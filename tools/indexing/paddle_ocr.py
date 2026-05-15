"""Shared PaddleOCR adapter and engine configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PADDLE_CACHE_DIR = PROJECT_ROOT / ".paddlex-cache"


def _mapping_from_result(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return value
    json_value = getattr(value, "json", None)
    if callable(json_value):
        try:
            json_value = json_value()
        except TypeError:
            json_value = None
    if isinstance(json_value, dict):
        return json_value
    return None


def _extract_ocr_texts(value: Any) -> list[str]:
    mapping = _mapping_from_result(value)
    if mapping is not None:
        res = mapping.get("res")
        if isinstance(res, dict):
            mapping = res
        for key in ("rec_texts", "texts"):
            texts = mapping.get(key)
            if isinstance(texts, list):
                return [str(text).strip() for text in texts if str(text).strip()]
        text = mapping.get("text")
        if isinstance(text, str) and text.strip():
            return [text.strip()]

    if isinstance(value, (list, tuple)):
        if len(value) >= 2:
            second = value[1]
            if isinstance(second, str) and second.strip():
                return [second.strip()]
            if isinstance(second, (list, tuple)) and second and isinstance(second[0], str):
                text = second[0].strip()
                return [text] if text else []
        out: list[str] = []
        for item in value:
            out.extend(_extract_ocr_texts(item))
        return out

    return []


class PaddleOcrAdapter:
    """Expose PaddleOCR through the small callable shape used by OCR scripts."""

    def __init__(self, ocr: Any):
        self._ocr = ocr

    def __call__(self, image_input: Any) -> tuple[list[tuple[None, str]], None]:
        if hasattr(self._ocr, "predict"):
            try:
                raw = self._ocr.predict(image_input)
            except TypeError:
                raw = self._ocr.predict(input=image_input)
        elif hasattr(self._ocr, "ocr"):
            raw = self._ocr.ocr(image_input)
        else:
            raise TypeError("PaddleOCR object has no predict or ocr method")
        return [(None, text) for text in _extract_ocr_texts(raw)], None


def create_paddle_ocr_engine() -> PaddleOcrAdapter:
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(PADDLE_CACHE_DIR))
    os.environ.setdefault("FLAGS_use_mkldnn", "false")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    from paddleocr import PaddleOCR

    options = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "text_detection_model_name": os.environ.get("PADDLE_OCR_DET_MODEL", "PP-OCRv5_mobile_det"),
        "text_recognition_model_name": os.environ.get("PADDLE_OCR_REC_MODEL", "PP-OCRv5_mobile_rec"),
        "device": os.environ.get("PADDLE_OCR_DEVICE", "cpu"),
        "engine": os.environ.get("PADDLE_OCR_ENGINE", "paddle_dynamic"),
        "enable_mkldnn": False,
        "enable_cinn": False,
    }
    try:
        return PaddleOcrAdapter(PaddleOCR(**options))
    except TypeError:
        return PaddleOcrAdapter(PaddleOCR())
