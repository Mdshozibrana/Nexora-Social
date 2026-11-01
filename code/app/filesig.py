"""File-signature (magic byte) checks — Phase 28, security §8.

The upload type was previously decided by the client-supplied MIME
type / file extension alone (tgupload.classify), so a renamed file
could claim to be a photo. These helpers look at the actual leading
bytes of the content; the upload path now requires the signature to
agree with the claimed kind before anything reaches Telegram."""
from typing import Optional

# ftyp brands that are still images (HEIC/HEIF/AVIF family).
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"mif2",
                b"msf1", b"avif", b"avis"}


def sniff(data: bytes) -> Optional[str]:
    """Classify raw bytes by their leading signature:
    'jpeg' | 'png' | 'webp' | 'heif' | 'mp4' | 'webm' | 'avi' | None.
    'mp4' covers the whole ISO-BMFF family (mp4/mov/3gp/m4v);
    'webm' covers the EBML family (webm/mkv)."""
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "avi"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[4:8] == b"ftyp":
        if data[8:12] in _HEIF_BRANDS:
            return "heif"
        return "mp4"
    return None


PHOTO_SIGNATURES = {"jpeg", "png", "webp", "heif"}
VIDEO_SIGNATURES = {"mp4", "webm", "avi"}


def matches(kind: str, data: bytes) -> bool:
    """True when the content signature agrees with the claimed kind."""
    sig = sniff(data)
    if kind == "photo":
        return sig in PHOTO_SIGNATURES
    if kind == "video":
        return sig in VIDEO_SIGNATURES
    return False
