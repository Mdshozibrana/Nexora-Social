"""Server-side video normalisation (Phase 19).

In-app uploads used to accept only MP4 files of at most 20 MB, which
real phone videos almost never are: a 30-second 1080p clip is typically
30-80 MB, iPhones hand out .mov files and some Android pickers .webm —
all of those failed with "cannot upload". The fix: accept the common
video containers up to a larger raw cap, then transcode to a compact
H.264 MP4 that fits Telegram's 20 MB getFile world before the file is
sent to Telegram via tgupload.

ffmpeg comes from (first hit wins): the FFMPEG_PATH env var, the
imageio-ffmpeg wheel (bundled binary — how Render gets one), or a
system ffmpeg on PATH. Without any ffmpeg, uploads fall back to the
original fast path: small MP4s only, everything else gets a clear
"cannot convert" error instead of a hang.
"""
import os
import re
import shutil
import subprocess

TARGET_MAX_BYTES = 19 * 1024 * 1024  # safely under Telegram's 20 MB
MAX_VIDEO_SECONDS = 240              # social clips; longer is rejected
MAX_HEIGHT = 720                     # social/Reels resolution is plenty


def find_ffmpeg():
    env = os.environ.get("FFMPEG_PATH")
    if env and os.path.exists(env):
        return env
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def probe_duration(path, ffmpeg=None):
    """Seconds (float) or None when the file cannot be probed."""
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            capture_output=True, text=True, timeout=30)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
                      proc.stderr or "")
        if not m:
            return None
        h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mnt * 60 + s
    except Exception:
        return None


class VideoError(Exception):
    """User-facing conversion failure; str(e) is shown to the member."""


def transcode_to_mp4(src_path, dst_path, ffmpeg=None):
    """Convert any supported video to a compact H.264 MP4 at dst_path.

    Returns the output size in bytes. Raises VideoError with a plain
    message when conversion is impossible, too long, or still too big.
    """
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        raise VideoError(
            "This video format cannot be processed right now — "
            "please try an MP4 clip")
    duration = probe_duration(src_path, ffmpeg)
    if duration is None or duration <= 0:
        raise VideoError("That file does not look like a playable video")
    if duration > MAX_VIDEO_SECONDS:
        raise VideoError(
            f"Video is too long — the maximum is {MAX_VIDEO_SECONDS // 60} "
            "minutes. Please trim it and try again")
    # Bitrate budget so the result fits TARGET_MAX_BYTES: total bits =
    # bytes*8/duration, minus a 96k audio track and safety margin.
    total_kbps = int(TARGET_MAX_BYTES * 8 / duration / 1000 * 0.92)
    video_kbps = max(250, min(3500, total_kbps - 96))
    # Cap the long side at 1280 and the short side at 720 (so 1080p
    # landscape becomes 1280x720 and 1080x1920 portrait 720x1280).
    vf = ("scale=w='if(gt(iw,ih),min(1280,iw),min(720,iw))':"
          "h='if(gt(iw,ih),min(720,ih),min(1280,ih))':"
          "force_original_aspect_ratio=decrease")
    cmd = [ffmpeg, "-y", "-i", src_path,
           "-vf", vf,
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps}k",
           "-bufsize", f"{video_kbps * 2}k",
           "-c:a", "aac", "-b:a", "96k", "-ac", "2",
           "-movflags", "+faststart", dst_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=900)
    except subprocess.TimeoutExpired:
        raise VideoError("Video processing timed out — please try a "
                         "shorter clip")
    except Exception:
        raise VideoError("Video processing failed — please try another clip")
    if proc.returncode != 0 or not os.path.exists(dst_path):
        raise VideoError("This video could not be converted — please try "
                         "another clip")
    size = os.path.getsize(dst_path)
    if size > 20 * 1024 * 1024:
        raise VideoError("Video is still too large after processing — "
                         "please try a shorter clip")
    return size
