"""Screen capture + Tesseract OCR for the Arabic Eye curtain.

Uses only the existing system toolchain: Pillow (ImageGrab) for capture,
pytesseract + installed Tesseract 5 (ara+eng) for recognition.
No downloads, no installs.
"""
from __future__ import annotations

from typing import List, Tuple

from PIL import Image, ImageGrab, ImageOps, ImageEnhance

try:
    import pytesseract
    from pytesseract import Output
    _HAS_TESSERACT = True
except Exception:
    _HAS_TESSERACT = False

try:
    import numpy as _np
    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False

_indra = None
_indra_failed = False


def _indra_converter():
    """Lazy singleton: indra-ocr CPU converter, or None when unusable."""
    global _indra, _indra_failed
    if _indra is not None or _indra_failed:
        return _indra
    try:
        import indra_ocr
        _indra = indra_ocr.load()
    except Exception:
        _indra = None
        _indra_failed = True
    return _indra


def _indra_lines(img: Image.Image) -> list | None:
    """OCR via indra-ocr (76MB, CPU, Arabic RTL). None -> use fallback."""
    if not _HAS_NUMPY:
        return None
    conv = _indra_converter()
    if conv is None:
        return None
    try:
        gray = ImageOps.grayscale(img)
        arr = _np.asarray(gray, dtype=_np.uint8)
        page = conv.ocr(arr)
        out = []
        for ln in page.lines:
            txt = (ln.text or "").strip()
            if not txt:
                continue
            conf = float(ln.conf) * 100.0
            if conf < 30:
                continue
            out.append((txt, conf))
        return out
    except Exception:
        return None


def capture_region(bbox: Tuple[int, int, int, int]) -> Image.Image:
    """Capture a screen region. bbox = (left, top, right, bottom)."""
    return ImageGrab.grab(bbox=bbox)


def frame_signature(img: Image.Image, size: Tuple[int, int] = (96, 54)):
    """Tiny grayscale fingerprint for change detection."""
    return ImageOps.grayscale(img).resize(size, Image.LANCZOS)


def change_ratio(a, b) -> float:
    """0.0 = identical frames. Pure stdlib-free pixel math via Pillow."""
    import itertools
    ha, hb = list(a.getdata()), list(b.getdata())
    n = max(1, min(len(ha), len(hb)))
    diff = sum(abs(x - y) for x, y in itertools.islice(zip(ha, hb), n))
    return (diff / n) / 255.0


def static_step(ratio: float, streak: int,
                still: float = 0.004) -> tuple[bool, int]:
    """Automatic pacing decision (pure, tested).

    Still frame -> skip OCR and grow the streak; motion resets it.
    Returns (do_read_now, new_streak).
    """
    if ratio < still:
        return (streak < 2), streak + 1
    return True, 0


def preprocess(img: Image.Image) -> Image.Image:
    """Upscale + grayscale + contrast + dark-background handling."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    img = img.resize((w * 2, h * 2), Image.LANCZOS)
    # Cap size: huge regions make Tesseract hang for many seconds.
    if img.size[0] > 1600:
        ratio = 1600 / img.size[0]
        img = img.resize(
            (1600, max(1, int(img.size[1] * ratio))), Image.LANCZOS
        )
    gray = ImageOps.grayscale(img)
    # Dark terminal background -> invert so text is dark on light.
    extrema = gray.getextrema()
    mean = sum(extrema) / 2 if isinstance(extrema, tuple) else extrema
    try:
        import numpy as _np  # noqa
        mean = float(_np.asarray(gray).mean())
    except Exception:
        pass
    if mean < 128:
        gray = ImageOps.invert(gray)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    # Gentle binary threshold to help Tesseract on terminal fonts.
    thr = gray.point(lambda p: 255 if p > 160 else 0, mode="L")
    return thr


def ocr_lines(img: Image.Image, lang: str = "ara+eng") -> List[Tuple[str, float]]:
    """Return [(line_text, mean_conf)] in reading order.

    Primary: indra-ocr (tiny CPU model with Arabic RTL). Fallback: Tesseract.
    """
    indra_out = _indra_lines(img)
    if indra_out is not None:
        return indra_out
    if not _HAS_TESSERACT:
        return []
    proc = preprocess(img)
    data = pytesseract.image_to_data(
        proc, lang=lang, config="--psm 6",
        output_type=Output.DICT,
    )
    lines: dict[tuple, list[str]] = {}
    confs: dict[tuple, list[float]] = {}
    n = len(data["text"])
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        try:
            c = float(data["conf"][i])
        except Exception:
            c = -1.0
        if c < 30:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(txt)
        confs.setdefault(key, []).append(c)
    out = []
    for key in sorted(lines):
        words = lines[key]
        cs = confs[key]
        out.append((" ".join(words), sum(cs) / max(len(cs), 1)))
    return out
