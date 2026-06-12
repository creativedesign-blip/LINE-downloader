"""Inspect & compare image encoding/metadata for false-positive ad-filter triage.

Purpose: a legitimate travel promo passes LINE when hand-made but gets wrongly
filtered when produced by the pipeline / an AI tool. LINE support asked to compare
the uploaded images vs the manual ones. This dumps the *non-pixel* characteristics
(format, color, DPI, EXIF/XMP/ICC, AI-provenance markers, JPEG encoder params) so
the difference is visible, and flags when a batch is byte-uniform in metadata.

Usage:
    python -m tools.branding.inspect_image_meta IMG1 [IMG2 ...]
    python -m tools.branding.inspect_image_meta blocked.jpg passing.jpg   # diff 2
    python -m tools.branding.inspect_image_meta path\\to\\folder\\*.jpg     # batch
"""

from __future__ import annotations

import glob
import hashlib
import sys
from pathlib import Path

from PIL import ExifTags, Image, JpegImagePlugin

# Raw-byte signatures that reveal AI-provenance / metadata blocks.
_BYTE_SIGNATURES = {
    "c2pa / Content Credentials": (b"c2pa", b"jumbf", b"urn:c2pa", b"contentauth"),
    "XMP packet": (b"<?xpacket", b"http://ns.adobe.com/xap/"),
    "IPTC AI source": (b"trainedAlgorithmicMedia", b"DigitalSourceType",
                       b"compositeWithTrainedAlgorithmicMedia"),
    "known AI tool tags": (b"Stable Diffusion", b"Midjourney", b"DALL", b"Firefly",
                           b"NovelAI", b"ComfyUI", b"automatic1111", b"GIMP",
                           b"Adobe", b"Photoshop"),
}


def _exif_software(img: Image.Image) -> dict:
    out = {}
    try:
        exif = img.getexif()
    except Exception:
        return out
    if not exif:
        return out
    wanted = {"Software", "Make", "Model", "DateTime", "Artist", "HostComputer"}
    name_by_id = {v: k for k, v in ExifTags.TAGS.items()}
    for name in wanted:
        tag = name_by_id.get(name)
        if tag is not None and tag in exif:
            out[name] = str(exif.get(tag))
    return out


def _raw_markers(path: Path) -> list[str]:
    try:
        blob = path.read_bytes()
    except OSError:
        return []
    found = []
    for label, sigs in _BYTE_SIGNATURES.items():
        if any(sig in blob for sig in sigs):
            found.append(label)
    return found


def inspect(path: Path) -> dict:
    info: dict = {"path": str(path)}
    try:
        size_bytes = path.stat().st_size
    except OSError:
        return {"path": str(path), "error": "cannot stat"}
    info["file_bytes"] = size_bytes

    try:
        with Image.open(path) as img:
            img.load()
            info["format"] = img.format
            info["mode"] = img.mode  # e.g. RGB, RGBA, CMYK, P
            info["size_wh"] = img.size
            info["dpi"] = tuple(round(v) for v in img.info.get("dpi", ())) or None
            info["has_icc"] = bool(img.info.get("icc_profile"))
            info["has_xmp"] = bool(img.info.get("xmp")) or "XMP packet" in _raw_markers(path)
            info["jfif"] = img.info.get("jfif")
            info["jfif_density"] = img.info.get("jfif_density")
            info["jfif_unit"] = img.info.get("jfif_unit")
            info["progressive"] = bool(img.info.get("progression") or img.info.get("progressive"))
            info["exif"] = _exif_software(img)
            if img.format == "JPEG":
                try:
                    samp = JpegImagePlugin.get_sampling(img)
                    info["chroma_subsampling"] = {0: "4:4:4", 1: "4:2:2", 2: "4:2:0"}.get(samp, samp)
                except Exception:
                    info["chroma_subsampling"] = "?"
                q = getattr(img, "quantization", None)
                if q:
                    flat = b"".join(bytes(q[k]) for k in sorted(q))
                    info["quant_table_hash"] = hashlib.sha1(flat).hexdigest()[:12]
    except Exception as e:  # noqa: BLE001 - report, don't crash on odd files
        info["error"] = f"{type(e).__name__}: {e}"
        return info

    info["raw_markers"] = _raw_markers(path)

    # Metadata fingerprint (encoder/provenance characteristics, NOT dimensions or
    # pixels). Files with the SAME fingerprint were produced identically.
    fp_fields = (
        info.get("format"), info.get("mode"), info.get("dpi"),
        info.get("has_icc"), info.get("has_xmp"), info.get("jfif_unit"),
        info.get("progressive"), info.get("chroma_subsampling"),
        info.get("quant_table_hash"), tuple(sorted(info.get("exif", {}).keys())),
        tuple(sorted(info.get("raw_markers", []))),
    )
    info["meta_fingerprint"] = hashlib.sha1(repr(fp_fields).encode()).hexdigest()[:12]
    return info


def _expand(args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for a in args:
        matches = glob.glob(a)
        paths.extend(Path(m) for m in matches) if matches else paths.append(Path(a))
    return paths


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    paths = _expand(argv)
    results = [inspect(p) for p in paths]

    for r in results:
        print("=" * 70)
        for k, v in r.items():
            print(f"  {k:18}: {v}")

    fps = {r.get("meta_fingerprint") for r in results if "error" not in r}
    print("=" * 70)
    if len(results) > 1:
        if len(fps) == 1:
            print(f"[!] All {len(results)} files share ONE metadata fingerprint "
                  f"({fps.pop()}) -> byte-uniform encoding/metadata across the batch.")
        else:
            print(f"[i] {len(results)} files span {len(fps)} distinct metadata "
                  f"fingerprints -> they differ. See fields above to spot how.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
