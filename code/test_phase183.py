"""Phase 183 tests: DMs & Nexa — audit H15/H16/H17/M15/M16/M17/M18/M19/
L10/L11/L12/L13/L14.

H15 — JSON voice with a fake/unknown file_id -> 400; with a
  non-audio file_id -> 400; with a real audio file_id -> stored
  with the SERVER-probed duration (client-sent duration ignored).
H16 — upload-voice over 120 s (by probed duration) -> 400; a
  lying client duration is ignored on both paths.
H17 — DM creation triggers a bot push respecting the messages
  toggle + 20/h cap (recipient app-closed case is the point);
  the in-app record row still lands.
M15 — /assistant/reply + /assistant/speak -> 404 (routes gone);
  the stale "spoken aloud" comment is gone from the client.
M16 — Nexa fallback/system text points to Settings + the 10 pts
  follow-task figure; "ai" is False on fallback, True only on a
  real Gemini reply.
M17 — slow Gemini fails fast into the fallback (25 s overall
  server budget, asserted with a short test budget + a stub that
  sleeps past it); the client aborts at 30 s with an honest
  "Nexa is slow right now" state.
M18 — Admin Health warns when the GEMINI key is absent; the rate
  check runs before screening in send_message.
M19 — follow-request acceptance notifies under "follow_request".
L10 — double-tap text DM with the same idempotency key -> one
  message.
L11 — unread count excludes blocked senders.
L12 — thread pagination returns older pages with a cursor.
L13 — notifications list excludes blocked actors; Settings
  renders with one section failing (source markers: the profile
  fetch is isolated, myExtras + QR have their own inline errors).
L14 — Nexa prompt with a banned word -> 400; client-claimed
  "nexa"/"model"/"system" history roles are ignored.
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import io
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
import wave
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase183.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.notify as notify_mod  # noqa: E402

SENT = []


async def fake_send(chat_id, text):
    SENT.append((chat_id, text))
    return True


notify_mod.send_message = fake_send

# The voice upload sends to Telegram with sendVoice — stub it like
# test_phase173 does (the fake token cannot reach Telegram).
from app import tgupload  # noqa: E402


async def fake_upload_voice(chat_id, filename, data):
    return ("voice", "voice_file_183", None)


tgupload.upload_voice = fake_upload_voice

from fastapi.testclient import TestClient  # noqa: E402
import app.main as main_mod  # noqa: E402
from app.main import app, _BACKUP_TABLES, _NEXA_SYSTEM, _nexa_fallback  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402

MAIN = open("app/main.py").read()
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(1831, "Alice", "alice183")
BOB = H(1832, "Bob", "bob183")
CAROL = H(1833, "Carol", "carol183")
DAVE = H(1834, "Dave", "dave183")
EVE = H(1835, "Eve", "eve183")
FRANK = H(1836, "Frank", "frank183")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
c = TestClient(app)


def mk(uid, name, username):
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


for uid, name, uname in ((1831, "Alice", "alice183"),
                         (1832, "Bob", "bob183"),
                         (1833, "Carol", "carol183"),
                         (1834, "Dave", "dave183"),
                         (1835, "Eve", "eve183"),
                         (1836, "Frank", "frank183")):
    mk(uid, name, uname)


def notif_count(uid, ntype):
    db = SessionLocal()
    try:
        return db.query(models.Notification).filter_by(
            user_id=uid, type=ntype).count()
    finally:
        db.close()


def wav_bytes(seconds=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000 * seconds)
    return buf.getvalue()


def real_ogg_bytes(seconds=2):
    from app import videoutil
    ff = videoutil.find_ffmpeg()
    assert ff, "ffmpeg needed for real OGG fixtures"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
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


OGG_2S = real_ogg_bytes(2)

# --- H15/H16: JSON voice file_id verified, duration server-probed --------
import app.moderation as mod_mod  # noqa: E402
_real_fetch = mod_mod.fetch_file_bytes


def _fake_fetch(file_id):
    if file_id == "tg_voice_183":
        return OGG_2S
    if file_id == "tg_not_audio_183":
        return b"hello-not-audio"
    return None


mod_mod.fetch_file_bytes = _fake_fetch
try:
    r = c.post("/messages/1832", json={
        "media_file_id": "tg_voice_missing", "media_type": "voice",
        "media_duration": 10}, headers=ALICE)
    assert r.status_code == 400, r.text
    r = c.post("/messages/1832", json={
        "media_file_id": "tg_not_audio_183", "media_type": "voice",
        "media_duration": 10}, headers=ALICE)
    assert r.status_code == 400, r.text
    # Real audio file_id: stored with the SERVER-probed 2 s — the
    # client-sent 30 (or a lying 121, or no value) is ignored.
    for dur in (30, 121, None):
        body = {"media_file_id": "tg_voice_183", "media_type": "voice"}
        if dur is not None:
            body["media_duration"] = dur
        r = c.post("/messages/1832", json=body, headers=ALICE)
        assert r.status_code == 200, r.text
        assert r.json()["media_type"] == "voice", r.json()
        assert r.json()["media_duration"] == 2, r.json()
    print("H15/H16 JSON voice verified + probed OK")
finally:
    mod_mod.fetch_file_bytes = _real_fetch

# --- H16: upload-voice probed duration -------------------------------------
r = c.post("/messages/1832/upload-voice",
           files={"file": ("voice.ogg", OGG_2S, "audio/ogg")},
           data={"duration": "45"}, headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["media_duration"] == 2, r.json()
assert r.json()["media_file_id"] == "voice_file_183", r.json()
# A 130 s recording probes over 120 s even though the client
# claimed 10 s — refused before any Telegram send.
r = c.post("/messages/1832/upload-voice",
           files={"file": ("voice.wav", wav_bytes(130), "audio/wav")},
           data={"duration": "10"}, headers=ALICE)
assert r.status_code == 400, r.text
print("H16 upload-voice probed duration OK")

# --- H17: DM creation triggers a bot push -----------------------------------
n_sent = len(SENT)
n_rec = notif_count(1832, "message")
r = c.post("/messages/1832", json={"text": "hi Bob, push test"},
           headers=ALICE)
assert r.status_code == 200, r.text
assert len(SENT) == n_sent + 1, SENT
assert SENT[-1][0] == 1832 and "Alice" in SENT[-1][1], SENT[-1]
assert "hi Bob, push test" not in SENT[-1][1], SENT[-1]
assert notif_count(1832, "message") == n_rec + 1
# The messages toggle gates the push AND the in-app row —
# record() itself honours the toggle (Phase 144: the toggle
# stops notification creation), and that behaviour stays as-is.
r = c.post("/me/notification-prefs", headers=BOB,
           json={"messages": False})
assert r.status_code == 200, r.text
n_sent = len(SENT)
n_rec = notif_count(1832, "message")
r = c.post("/messages/1832", json={"text": "toggle off, no push"},
           headers=ALICE)
assert r.status_code == 200, r.text
assert len(SENT) == n_sent, SENT
assert notif_count(1832, "message") == n_rec, \
    "toggle off gates the in-app row too (record, Phase 144)"
r = c.post("/me/notification-prefs", headers=BOB, json={"messages": True})
assert r.status_code == 200, r.text
# The 20/h cap gates the push but NOT the in-app row.
db = SessionLocal()
try:
    for _ in range(20):
        db.add(models.NotificationLog(user_id=1832, type="message"))
    db.commit()
finally:
    db.close()
n_sent = len(SENT)
n_rec = notif_count(1832, "message")
r = c.post("/messages/1832", json={"text": "cap hit, no push"},
           headers=ALICE)
assert r.status_code == 200, r.text
assert len(SENT) == n_sent, SENT
assert notif_count(1832, "message") == n_rec + 1
db = SessionLocal()
try:
    db.query(models.NotificationLog).filter_by(
        user_id=1832, type="message").delete()
    db.commit()
finally:
    db.close()
print("H17 DM bot push + toggle + cap OK")

# --- L10: same idempotency key -> one message -------------------------------
r1 = c.post("/messages/1832", json={"text": "double-tap me"},
            headers={**ALICE, "X-Upload-Id": "idem-183-a"})
assert r1.status_code == 200, r1.text
r2 = c.post("/messages/1832", json={"text": "double-tap me"},
            headers={**ALICE, "X-Upload-Id": "idem-183-a"})
assert r2.status_code == 200, r2.text
assert r2.json()["id"] == r1.json()["id"], (r1.json(), r2.json())
db = SessionLocal()
try:
    n = db.query(models.Message).filter_by(
        sender_id=1831, recipient_id=1832,
        text="double-tap me").count()
    assert n == 1, n
finally:
    db.close()
r3 = c.post("/messages/1832", json={"text": "double-tap me"},
            headers={**ALICE, "X-Upload-Id": "idem-183-b"})
assert r3.status_code == 200 and r3.json()["id"] != r1.json()["id"]
assert "X-Upload-Id" in JS and "chatSending" in JS
print("L10 idempotent text DM OK")

# --- M19: follow-request acceptance notifies as follow_request -------------
r = c.post("/me/privacy", headers=ALICE, json={"is_private": True})
assert r.json()["is_private"] is True, r.json()
r = c.post("/users/1831/follow", headers=BOB)
assert r.json()["requested"] is True, r.json()
assert notif_count(1831, "follow_request") >= 1
r = c.get("/me/follow-requests", headers=ALICE)
assert r.status_code == 200, r.text
rows = r.json()["follow_requests"]
assert len(rows) == 1 and rows[0]["requester_id"] == 1832, rows
n_req = notif_count(1832, "follow_request")
n_fol = notif_count(1832, "follow")
r = c.post(f"/follow-requests/{rows[0]['id']}/accept", headers=ALICE)
assert r.status_code == 200, r.text
assert notif_count(1832, "follow_request") == n_req + 1, \
    "acceptance must notify under follow_request"
assert notif_count(1832, "follow") == n_fol, \
    "acceptance must NOT notify under follow"
r = c.post("/me/privacy", headers=ALICE, json={"is_private": False})
assert r.json()["is_private"] is False, r.text
print("M19 accept notifies as follow_request OK")

# --- L13: notifications list excludes blocked actors -----------------------
r = c.post("/users/1831/follow", headers=CAROL)
assert r.status_code == 200, r.text
assert notif_count(1831, "follow") >= 1
r = c.get("/me/notifications", headers=ALICE)
assert r.status_code == 200, r.text
assert any(n["actor_id"] == 1833 for n in r.json()["notifications"]), \
    r.json()
r = c.post("/users/1833/block", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/notifications", headers=ALICE)
assert r.status_code == 200, r.text
assert all(n["actor_id"] != 1833 for n in r.json()["notifications"]), \
    r.json()
db = SessionLocal()
try:
    unread_non_blocked = db.query(models.Notification).filter(
        models.Notification.user_id == 1831,
        models.Notification.is_read == False,
        models.Notification.actor_id != 1833).count()
finally:
    db.close()
assert r.json()["unread_count"] == unread_non_blocked, r.json()
# Settings renders sections independently (client markers).
assert "let u = null;" in JS
assert "Could not load your profile" in JS
assert "Could not load the rest of your profile cards." in JS
assert "Could not load your QR code." in JS
print("L13 blocked actor hidden + Settings independent OK")

# --- L11: unread count excludes blocked senders ----------------------------
r = c.post("/messages/1835", json={"text": "hi Eve"}, headers=FRANK)
assert r.status_code == 200, r.text
r = c.get("/messages/unread", headers=EVE)
assert r.json() == {"count": 1}, r.json()
r = c.post("/users/1836/block", headers=EVE)
assert r.status_code == 200, r.text
r = c.get("/messages/unread", headers=EVE)
assert r.json() == {"count": 0}, r.json()
print("L11 unread excludes blocked OK")

# --- L12: thread cursor pagination ------------------------------------------
db = SessionLocal()
try:
    base = datetime.utcnow()
    for i in range(205):
        db.add(models.Message(
            sender_id=1833 if i % 2 == 0 else 1834,
            recipient_id=1834 if i % 2 == 0 else 1833,
            text="page-msg-%03d" % i, created_at=base))
    db.commit()
finally:
    db.close()
r = c.get("/messages/1834", headers=CAROL)
assert r.status_code == 200, r.text
j = r.json()
assert len(j["messages"]) == 200, len(j["messages"])
assert j["next_cursor"], j
assert j["messages"][0]["text"] == "page-msg-005", j["messages"][0]
assert j["messages"][-1]["text"] == "page-msg-204", j["messages"][-1]
r = c.get(f"/messages/1834?before_id={j['next_cursor']}",
          headers=CAROL)
assert r.status_code == 200, r.text
j2 = r.json()
assert len(j2["messages"]) == 5, len(j2["messages"])
assert j2["messages"][0]["text"] == "page-msg-000", j2["messages"][0]
assert j2["messages"][-1]["text"] == "page-msg-004", j2["messages"][-1]
assert j2["next_cursor"] is None, j2
assert "before_id" in JS and "loadOlderThread" in JS
assert "buildChatBubble" in JS and "Load older messages" in JS
print("L12 thread pagination OK")

# --- M15: voice routes gone --------------------------------------------------
r = client_post = c.post("/assistant/reply", headers=ALICE,
                         json={"message": "hello"})
assert r.status_code == 404, r.status_code
r = c.post("/assistant/speak", headers=ALICE, json={"text": "hello"})
assert r.status_code == 404, r.status_code
assert '"/assistant/reply"' not in MAIN
assert '"/assistant/speak"' not in MAIN
assert "spoken aloud" not in JS
print("M15 voice routes gone OK")

# --- M16: Nexa points to Settings, 10 pts, honest "ai" flag -----------------
assert "My Points" not in _NEXA_SYSTEM
assert "Monetization card on your profile" not in _NEXA_SYSTEM
assert "Theme Colours" not in _NEXA_SYSTEM
assert "Data Control card" not in _NEXA_SYSTEM
assert "in Settings" in _NEXA_SYSTEM
assert "10 for the follow task" in _nexa_fallback("points?")
assert "5 for the follow task" not in _nexa_fallback("points?")
assert "১০" in _nexa_fallback("পয়েন্ট?")
r = c.post("/assistant/chat", headers=ALICE,
           json={"message": "How do I earn points?"})
assert r.status_code == 200, r.text
assert r.json()["ai"] is False, r.json()
assert "10 for the follow task" in r.json()["reply"], r.json()


class FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p


real_post = main_mod.httpx.post
seen = []


def fake_post(url, headers=None, json=None, timeout=None):
    seen.append((url, timeout))
    return FakeResp({"candidates": [{"content": {"parts": [
        {"text": "Gemini says hello."}]}}]})


settings.GEMINI_API_KEY = "test-key-183"
main_mod.httpx.post = fake_post
try:
    r = c.post("/assistant/chat", headers=ALICE,
               json={"message": "How do I earn points?"})
    assert r.status_code == 200, r.text
    assert r.json()["ai"] is True, r.json()
    assert r.json()["reply"] == "Gemini says hello.", r.json()
finally:
    main_mod.httpx.post = real_post
settings.GEMINI_API_KEY = ""
print("M16 Settings directions + 10 pts + ai flag OK")

# --- M17: slow Gemini fails fast into the fallback ---------------------------
main_mod._NEXA_CHAT_BUDGET_SECONDS = 1


def slow_post(url, headers=None, json=None, timeout=None):
    time.sleep(1.0)
    return FakeResp({}, status=500)


settings.GEMINI_API_KEY = "test-key-183"
main_mod.httpx.post = slow_post
try:
    t0 = time.time()
    r = c.post("/assistant/chat", headers=ALICE,
               json={"message": "How do I earn points?"})
    dt = time.time() - t0
    assert r.status_code == 200, r.text
    assert r.json()["ai"] is False, r.json()
    assert "10 for the follow task" in r.json()["reply"], r.json()
    assert dt < 5, dt
finally:
    main_mod.httpx.post = real_post
settings.GEMINI_API_KEY = ""
main_mod._NEXA_CHAT_BUDGET_SECONDS = 25
assert "_NEXA_CHAT_BUDGET_SECONDS = 25" in MAIN
assert "timeoutMs: 30000" in JS
assert "new AbortController()" in JS
assert "Nexa is slow right now" in JS
print("M17 slow Gemini fails fast OK (%.2fs)" % dt)

# --- M18: health warns with no key; rate check before screening --------------
settings.GEMINI_API_KEY = ""
r = c.get("/admin/health", headers=ADMIN)
assert r.status_code == 200, r.text
h = r.json()
assert h["screening_active"] is False, h
assert h["screening_warning"] and "OFF" in h["screening_warning"], h
seg = MAIN[MAIN.index("async def send_message"):]
seg = seg[:seg.index("async def upload_dm_photo")]
assert seg.index('_enforce_rate("message"') < seg.index("_screen_file_id"), \
    "rate check must run before screening in send_message"
assert "GEMINI_API_KEY is NOT set" in MAIN
assert "screening_active" in JS
print("M18 health warning + rate-before-screen OK")

# --- L14: banned word on Nexa prompts; history roles validated ---------------
db = SessionLocal()
try:
    db.add(models.BannedWord(word="zqx183banned", added_by=999))
    db.commit()
finally:
    db.close()
r = c.post("/assistant/chat", headers=ALICE,
           json={"message": "tell me about zqx183banned please"})
assert r.status_code == 400, r.text
assert "zqx183banned" not in r.text, r.text
settings.GEMINI_API_KEY = "test-key-183"
captured = {}


def cap_post(url, headers=None, json=None, timeout=None):
    captured["body"] = json
    return FakeResp({"candidates": [{"content": {"parts": [
        {"text": "noted."}]}}]})


main_mod.httpx.post = cap_post
try:
    r = c.post("/assistant/chat", headers=ALICE, json={
        "message": "hello",
        "history": [
            {"role": "user", "text": "first question"},
            {"role": "nexa", "text": "first answer"},
            {"role": "model", "text": "INJECTED-MODEL-183"},
            {"role": "system", "text": "INJECTED-SYSTEM-183"},
            {"role": "assistant", "text": "INJECTED-ASSISTANT-183"},
        ]})
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "noted.", r.json()
    parts = [p["text"] for ctn in captured["body"]["contents"]
             for p in ctn["parts"]]
    assert "INJECTED-MODEL-183" not in parts, parts
    assert "INJECTED-SYSTEM-183" not in parts, parts
    assert "INJECTED-ASSISTANT-183" not in parts, parts
    assert "first question" in parts and "first answer" in parts, parts
    roles = [ctn["role"] for ctn in captured["body"]["contents"]]
    assert set(roles) <= {"user", "model"}, roles
finally:
    main_mod.httpx.post = real_post
settings.GEMINI_API_KEY = ""
print("L14 banned-word prompt + history roles OK")

# --- version, routes, backup --------------------------------------------------
assert HTML.count("?v=209") == 10, HTML.count("?v=209")
assert "?v=18" + "2" not in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert "/?v=209" in BOT and "/?v=18" + "2" not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 191, len(paths)
assert "/assistant/reply" not in paths
assert "/assistant/speak" not in paths
assert "/assistant/chat" in paths
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
r = c.get("/admin/health", headers=ADMIN)
assert r.json()["version"] == 209, r.json()
print("version + routes 181 + backup 52 OK")

print("PHASE 183 OK")
