"""Image conversion for phone-camera formats (Phase 26).

Modern phones (Samsung "high efficiency", iPhone) save photos as
HEIC/HEIF, which Telegram's sendPhoto and web browsers cannot use
directly. Such uploads are converted to JPEG before they go
anywhere. Conversion uses Pillow + pillow-heif (libheif wheel).
"""
from io import BytesIO

HEIF_MIMES = {"image/heic", "image/heif", "image/heif-sequence",
              "image/heic-sequence"}
HEIF_EXTS = {"heic", "heif"}


def is_heif(content_type: str, filename: str = "") -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in HEIF_MIMES:
        return True
    ext = (filename or "").rsplit(".", 1)[-1].strip().lower()
    return ext in HEIF_EXTS


def to_jpeg(data: bytes) -> bytes:
    """Decode HEIC/HEIF bytes and return JPEG bytes (quality 88).
    Raises whatever Pillow raises on undecodable input; the caller
    turns that into a friendly 400."""
    from PIL import Image
    from pillow_heif import register_heif_opener
    register_heif_opener()
    im = Image.open(BytesIO(data))
    im.load()
    out = BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=88)
    return out.getvalue()
