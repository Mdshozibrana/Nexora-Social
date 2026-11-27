"""Phase 173 tests: DM voice messages.

POST /messages/{uid}/upload-voice accepts an audio recording
(OGG passthrough, anything else transcoded to OGG Opus with
ffmpeg) and sends it with Telegram sendVoice; the message
carries media_type='voice' + media_duration (1-120 s, 5 MB
cap). Phase 183 (audit H15/H16): the duration is the SERVER-
probed one — the client-sent value is ignored on both paths —
and the JSON path FETCHES + VERIFIES the voice file_id
(exists, OggS, probes to 1-120 s) before storing it. Voice
is never Gemini-screened.
Client: mic button, voice bubble with play/pause + progress
+ duration, thread preview, poll pauses while playing.
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase173.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _run_scheduled_sweep  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import ratelimit  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(1731, "Alice", "alice")
BOB = H(1732, "Bob", "bob")
CAROL = H(1733, "Carol", "carol")
DAVE = H(1734, "Dave", "dave")
EVE = H(1735, "Eve", "eve")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()

c = TestClient(app)


def mk(uid, name, username):
    """Create the user row (first authed call) and pin the username
    directly, so mention lookup never depends on auth upsert."""
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        u = db.get(models.User, uid)
        assert u is not None, "user %s not created" % uid
        u.username = username
        db.commit()
    finally:
        db.close()


for uid, name, uname in ((1731, "Alice", "alice"), (1732, "Bob", "bob"),
                         (1733, "Carol", "carol"), (1734, "Dave", "dave"),
                         (1735, "Eve", "eve")):
    mk(uid, name, uname)


# --- voice test helpers ----------------------------------------------------
import io
import wave

from app import tgupload  # noqa: E402
from app.main import _media_visible  # noqa: E402

CAPTURED = {}


async def fake_upload_voice(chat_id, filename, data):
    CAPTURED["chat_id"] = chat_id
    CAPTURED["filename"] = filename
    CAPTURED["data"] = data
    return ("voice", "voice_file_173", None)


tgupload.upload_voice = fake_upload_voice


def ogg_bytes():
    return b"OggS" + b"\x00" * 200


def real_ogg_bytes(seconds=2):
    """A REAL OGG Opus file (transcoded with the bundled
    ffmpeg), so the server can probe its duration — the fake
    OggS bytes below cannot be probed and are refused
    (Phase 183, audit H16)."""
    import subprocess
    import tempfile
    from app import videoutil
    ff = videoutil.find_ffmpeg()
    assert ff, "ffmpeg needed for real OGG fixtures"
    with tempfile.NamedTemporaryFile(delete=False,
                                     suffix=".wav") as f:
        f.write(wav_bytes(seconds))
        src = f.name
    dst = src + ".ogg"
    r = subprocess.run([ff, "-y", "-i", src, "-vn", "-c:a", "libopus",
                        "-b:a", "32k", dst],
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    with open(dst, "rb") as fh:
        data = fh.read()
    for p in (src, dst):
        try:
            os.unlink(p)
        except OSError:
            pass
    return data


def wav_bytes(seconds=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000 * seconds)
    return buf.getvalue()


def voice_upload(uid_headers, uid, data, filename, ctype, duration):
    return c.post(
        f"/messages/{uid}/upload-voice",
        files={"file": (filename, data, ctype)},
        data={"duration": str(duration)},
        headers=uid_headers)


def thread_with(uid_headers, uid):
    r = c.get(f"/messages/{uid}", headers=uid_headers)
    assert r.status_code == 200, r.text
    return r.json()["messages"]


def msg_count():
    db = SessionLocal()
    try:
        return db.query(models.Message).count()
    finally:
        db.close()


# 1. OGG voice upload: stored as voice + SERVER-probed duration,
# visible in thread. The client-sent 45 is IGNORED (Phase 183,
# audit H16) — the real 2 s recording stores 2.
OGG_2S = real_ogg_bytes(2)
r = voice_upload(ALICE, 1732, OGG_2S, "voice.ogg", "audio/ogg", 45)
assert r.status_code == 200, r.text
body = r.json()
assert body["media_type"] == "voice", body
assert body["media_duration"] == 2, body
assert body["media_file_id"] == "voice_file_173", body
assert body["text"] == "", body
assert CAPTURED["data"] == OGG_2S
assert CAPTURED["filename"] == "voice.ogg"
msgs = thread_with(ALICE, 1732)
assert len(msgs) == 1 and msgs[0]["media_type"] == "voice", msgs
assert msgs[0]["media_duration"] == 2, msgs
db = SessionLocal()
try:
    n = db.query(models.Notification).filter_by(
        user_id=1732, type="message").count()
    assert n >= 1, "voice DM notification missing"
finally:
    db.close()
print("1. OGG voice upload OK")

# 2. Validation: duration bounds, non-audio, size cap, self/404/block.
# Phase 183 (audit H16): the client-sent duration is ignored —
# a missing value, 0 or 121 with a real 2 s recording all store
# the probed 2 s. Only the PROBED duration can refuse a note.
r = c.post("/messages/1732/upload-voice",
           files={"file": ("voice.ogg", OGG_2S, "audio/ogg")},
           data={}, headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["media_duration"] == 2, r.json()
r = voice_upload(ALICE, 1732, OGG_2S, "voice.ogg", "audio/ogg", 0)
assert r.status_code == 200, r.text
r = voice_upload(ALICE, 1732, OGG_2S, "voice.ogg", "audio/ogg", 121)
assert r.status_code == 200, r.text
# A recording the server cannot probe is refused, not stored
# with a guessed duration — fake OggS bytes have no duration.
r = voice_upload(ALICE, 1732, ogg_bytes(), "voice.ogg", "audio/ogg", 10)
assert r.status_code == 400, r.text
# A low-bitrate file under 5 MB that probes over 120 s is
# refused even though the client claimed 10 s (130 s WAV).
r = voice_upload(ALICE, 1732, wav_bytes(130), "voice.wav",
                 "audio/wav", 10)
assert r.status_code == 400, r.text
r = voice_upload(ALICE, 1732, b"hello", "note.txt", "text/plain", 10)
assert r.status_code == 400, r.text
r = voice_upload(ALICE, 1732, b"x" * (5 * 1024 * 1024 + 1),
                 "voice.ogg", "audio/ogg", 10)
assert r.status_code == 400, r.text
r = voice_upload(ALICE, 1731, ogg_bytes(), "voice.ogg", "audio/ogg", 10)
assert r.status_code == 400, r.text
r = voice_upload(ALICE, 9999, ogg_bytes(), "voice.ogg", "audio/ogg", 10)
assert r.status_code == 404, r.text
r = c.post("/users/1735/block", headers=ALICE)
assert r.status_code == 200, r.text
r = voice_upload(ALICE, 1735, ogg_bytes(), "voice.ogg", "audio/ogg", 10)
assert r.status_code == 403, r.text
print("2. voice upload validation OK")

# 3. Non-OGG recording is transcoded to OGG Opus by real ffmpeg.
# Phase 183 (audit H16): the client claimed 7 s for a 1 s
# recording — the server stores the probed 1 s.
r = voice_upload(ALICE, 1732, wav_bytes(1), "voice.wav", "audio/wav", 7)
assert r.status_code == 200, r.text
assert r.json()["media_type"] == "voice", r.text
assert r.json()["media_duration"] == 1, r.text
assert CAPTURED["data"][:4] == b"OggS", CAPTURED["data"][:8]
assert len(CAPTURED["data"]) > 100, len(CAPTURED["data"])
print("3. WAV -> OGG Opus transcode OK")

# 4. JSON path: the voice file_id is FETCHED + VERIFIED
# server-side (Phase 183, audit H15) and the duration is the
# server-probed one (H16) — the client-sent value is ignored.
import app.moderation as mod_mod
_real_fetch = mod_mod.fetch_file_bytes


def _fake_fetch(file_id):
    if file_id == "tg_voice_9":
        return OGG_2S
    if file_id == "tg_not_audio":
        return b"hello-not-audio"
    return None


mod_mod.fetch_file_bytes = _fake_fetch
try:
    r = c.post("/messages/1732", json={
        "media_file_id": "tg_voice_9", "media_type": "voice",
        "media_duration": 30}, headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["media_type"] == "voice", r.text
    assert r.json()["media_duration"] == 2, r.text
    # No duration, or a lying 121, with a real 2 s file: the
    # client value is ignored, the probed 2 s is stored.
    r = c.post("/messages/1732", json={
        "media_file_id": "tg_voice_9", "media_type": "voice"},
        headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["media_duration"] == 2, r.text
    r = c.post("/messages/1732", json={
        "media_file_id": "tg_voice_9", "media_type": "voice",
        "media_duration": 121}, headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["media_duration"] == 2, r.text
    # Unknown file_id, and a file_id that is not audio, are 400.
    r = c.post("/messages/1732", json={
        "media_file_id": "tg_voice_missing", "media_type": "voice",
        "media_duration": 10}, headers=ALICE)
    assert r.status_code == 400, r.text
    r = c.post("/messages/1732", json={
        "media_file_id": "tg_not_audio", "media_type": "voice",
        "media_duration": 10}, headers=ALICE)
    assert r.status_code == 400, r.text
finally:
    mod_mod.fetch_file_bytes = _real_fetch
r = c.post("/messages/1732", json={
    "media_file_id": "tg_video_1", "media_type": "video"},
    headers=ALICE)
assert r.status_code == 400, r.text
r = c.post("/messages/1732", json={
    "media_file_id": "tg_photo_1", "media_type": "photo"},
    headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["media_type"] == "photo", r.text
assert r.json()["media_duration"] is None, r.text
print("4. JSON voice path OK")

# 5. Voice file visibility: participants only, like DM photos.
db = SessionLocal()
try:
    assert _media_visible(db, 1731, "voice_file_173") is True
    assert _media_visible(db, 1732, "voice_file_173") is True
    assert _media_visible(db, 1733, "voice_file_173") is False
    assert _media_visible(db, 1731, "no_such_file") is False
finally:
    db.close()
print("5. voice media visibility OK")

# 6. Client markers, version, routes, backup tables.
JS_MARKS = ["chat-mic", "voiceBubble", "fmtDur", "toggleVoiceRec",
            "upload-voice", "bubble-voice", "voice-play",
            "voicePlaying", "MediaRecorder", "🎤 Voice message",
            "stopVoiceRec", "sendVoiceNote"]
for m in JS_MARKS:
    assert m in JS, f"missing JS marker: {m}"
assert ".bubble-voice" in CSS and ".voice-track" in CSS
assert 'id="chat-mic"' in HTML
assert HTML.count("?v=202") == 10, HTML.count("?v=202")
# Split so the sweep never rewrites the negative: ?v=182 is gone.
assert "?v=18" + "2" not in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert "/?v=202" in BOT and "/?v=18" + "2" not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 193, len(paths)
assert "/messages/{uid}/upload-voice" in paths
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
b = r.json()
assert len(b["tables"]) == 55, len(b["tables"])
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
print("6. client + version + routes + backup OK")

print("PHASE 173 OK")
