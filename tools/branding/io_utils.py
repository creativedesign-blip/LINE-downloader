"""Unicode-safe image I/O for Windows paths containing non-ASCII characters.

cv2.imread and cv2.imwrite fail silently (return None / False) on Windows
when the path contains characters outside the system codepage. The project
root contains Chinese characters (e.g. "大都會"), so all image I/O in the
branding pipeline MUST go through these helpers.

Mirrors filter/filter.py:72-80 but generalized (supports flags argument
and returns None on failure instead of raising, for caller-controlled error
handling).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def imread_unicode(
    path: Path,
    flags: int = cv2.IMREAD_UNCHANGED,
) -> Optional[np.ndarray]:
    """Read an image from a path that may contain non-ASCII characters.

    Args:
        path: absolute or relative path to the image file.
        flags: cv2 flags. Use IMREAD_COLOR for base photos (drops alpha),
            IMREAD_UNCHANGED for logos (preserves alpha).

    Returns:
        numpy ndarray on success, None on failure (file missing, unreadable,
        or unsupported format).
    """
    try:
        with open(path, "rb") as f:
            buf = f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return None

    if not buf:
        return None

    arr = np.frombuffer(buf, dtype=np.uint8)
    img = cv2.imdecode(arr, flags)
    return img


def sidecar_of(image_path: Path) -> Path:
    """Return `<image>.json` sidecar path (e.g. foo.jpg -> foo.jpg.json)."""
    return image_path.with_suffix(image_path.suffix + ".json")


def image_of_sidecar(sidecar_path: Path) -> Path:
    """Return the image path a `<image>.json` sidecar refers to."""
    return sidecar_path.with_suffix("")


def load_sidecar(image_path: Path) -> dict:
    """Read the JSON sidecar for an image; missing/corrupt → empty dict."""
    sp = sidecar_of(image_path)
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_sidecar(image_path: Path, data: dict) -> None:
    """Write the JSON sidecar for an image (UTF-8, indent=2, trailing newline)."""
    sp = sidecar_of(image_path)
    sp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def imwrite_unicode(
    path: Path,
    img: np.ndarray,
    ext: str = ".jpg",
    quality: int = 92,
) -> bool:
    """Write an image to a path that may contain non-ASCII characters.

    Creates parent directories as needed.

    Args:
        path: destination path. Suffix is overridden by `ext` if differs.
        img: uint8 BGR or BGRA ndarray.
        ext: file extension including the leading dot (e.g. ".jpg", ".png").
        quality: JPEG quality 1-100. Ignored for PNG.

    Returns:
        True on success, False on encode or write failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    ext = ext.lower()
    if ext in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    elif ext == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
    else:
        params = []

    try:
        ok, buf = cv2.imencode(ext, img, params)
    except cv2.error:
        return False
    if not ok:
        return False

    try:
        with open(path, "wb") as f:
            f.write(buf.tobytes())
    except (PermissionError, OSError):
        return False

    return True
