"""Phase 81 — AI media screening (owner's rule: no adult or
graphic content may ever become a post).

Every photo or video that would become public content — a feed
post (Mini App upload, bot-chat post, or the JSON endpoint) or a
story — is classified BEFORE it is posted. Adult/sexual content
and gore (blood, wounds, graphic violence) are rejected outright:
the post is never created and the member is told why. Video is
screened by classifying three frames (10% / 50% / 90%).

The classifier is Gemini vision, using the same key and model
chain as Nexa (app/main.py's _gemini_chat). Screening is ACTIVE
only when GEMINI_API_KEY is configured — the same on/off pattern
as Nexa's AI mode. When active it fails CLOSED: media that cannot
be classified (every model errored, frames unreadable, download
failed) is not posted either; the member is asked to retry.

Verdicts are the strings "clean", "adult", "gore", "error".
Callers must treat anything other than "clean" as a rejection
while screening is active.
"""
import base64
import json
import logging
import subprocess

import httpx

from .config import settings

log = logging.getLogger("nexora.moderation")

MODELS = ("gemini-3-flash-preview", "gemini-3.8-flash",
          "gemini-flash-latest")

_PROMPT = (
    "You are a strict content-safety classifier for a family "
    "social app. Examine this image and reply with ONLY a JSON "
    "object, no other text: {\"adult\": true or false, "
    "\"gore\": true or false}. adult = nudity, sexual acts, or "
    "sexually explicit or provocative posing. gore = graphic "
    "blood, open wounds, dead bodies, torture, or extreme "
    "violence. Ordinary photos of clothed people, sports, food, "
    "animals, nature and objects are false for both. If graphic "
    "injury or blood is clearly present, gore is true.")

_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/webp",
                   "image/gif"}


def active():
    """Screening runs only when a Gemini key is configured."""
    return bool(settings.GEMINI_API_KEY)


def _verdict_from_reply(text):
    """Parse the classifier's JSON reply into a verdict."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except Exception:
        return None
    if obj.get("gore"):
        return "gore"
    if obj.get("adult"):
        return "adult"
    if "adult" in obj or "gore" in obj:
        return "clean"
    return None


def classify_image(data, mime="image/jpeg"):
    """Classify one image's bytes. Returns a verdict string;
    "error" when every model failed or refused to answer."""
    if not active():
        return "clean"
    if mime not in _SUPPORTED_MIME:
        mime = "image/jpeg"
    body = {
        "contents": [{"role": "user", "parts": [
            {"text": _PROMPT},
            {"inline_data": {
                "mime_type": mime,
                "data": base64.b64encode(data).decode("ascii")}}]}],
        "generationConfig": {"maxOutputTokens": 200,
                             "temperature": 0,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    for model in MODELS:
        try:
            r = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model}:generateContent",
                headers={"x-goog-api-key": settings.GEMINI_API_KEY},
                json=body, timeout=25)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        try:
            payload = r.json()
        except Exception:
            continue
        # Gemini's own safety filter refusing the image is itself
        # a strong signal — treat it as unsafe, never as clean.
        feedback = payload.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            return "adult"
        candidates = payload.get("candidates") or []
        if not candidates:
            continue
        cand = candidates[0]
        if cand.get("finishReason") == "SAFETY":
            return "adult"
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        verdict = _verdict_from_reply(text)
        if verdict:
            return verdict
    return "error"


def _frame_jpegs(path):
    """Up to three JPEG frames (10/50/90%) of a video file."""
    from . import videoutil
    ffmpeg = videoutil.find_ffmpeg()
    if not ffmpeg:
        return []
    dur = videoutil.probe_duration(path, ffmpeg) or 0
    times = ([dur * 0.1, dur * 0.5, dur * 0.9] if dur > 2
             else [0.5, 2.0, 4.0])
    frames = []
    for t in times:
        try:
            r = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error",
                 "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                 "-q:v", "4", "-f", "image2pipe", "-vcodec",
                 "mjpeg", "pipe:1"],
                capture_output=True, timeout=30)
        except Exception:
            continue
        if r.returncode == 0 and len(r.stdout) > 2000:
            frames.append(r.stdout)
    return frames


def screen_video(path):
    """Classify a video file by three of its frames."""
    if not active():
        return "clean"
    frames = _frame_jpegs(path)
    if not frames:
        return "error"
    for frame in frames:
        verdict = classify_image(frame, "image/jpeg")
        if verdict != "clean":
            return verdict
    return "clean"


def fetch_file_bytes(file_id):
    """Download a Telegram file's bytes (bot getFile, <=20 MB).
    Returns None when the file cannot be fetched."""
    api = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    try:
        with httpx.Client(timeout=30) as client:
            info = client.get(f"{api}/getFile",
                              params={"file_id": file_id})
            if info.status_code != 200:
                return None
            file_path = info.json()["result"]["file_path"]
            r = client.get(
                f"https://api.telegram.org/file/bot"
                f"{settings.BOT_TOKEN}/{file_path}")
            if r.status_code != 200:
                return None
            return r.content
    except Exception:
        return None


def block_message(kind, verdict):
    """The user-facing reason a piece of media was not posted."""
    what = "video" if kind == "video" else "photo"
    if verdict == "adult":
        return (f"🚫 This {what} wasn't posted — adult or sexual "
                "content isn't allowed on Nexora Social.")
    if verdict == "gore":
        return (f"🚫 This {what} wasn't posted — graphic, bloody "
                "or violent content isn't allowed on Nexora Social.")
    return ("⚠️ We couldn't safety-check this media just now — "
            "please try again in a moment.")
