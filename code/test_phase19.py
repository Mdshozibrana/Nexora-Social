"""Phase-19 tests: (A) the video-upload repair — MOV/WebM and oversize
MP4s are transcoded to MP4 by the real ffmpeg before the Telegram
send, small MP4s pass through byte-identical, raw caps and type checks
hold; (B) the admin dashboard — country/language captured at sign-in,
heartbeat time tracking, ad-impression counting, /admin/dashboard
aggregates and the /admin/users/{id} detail view.

Telegram sends are stubbed with a capturing fake (no network); the
transcoder runs for real on tiny generated clips. GeoIP is stubbed.
"""
import hashlib, hmac, json, os, shutil, subprocess, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase19.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import geoip, tgupload

SENT = {}

async def fake_upload(chat_id, filename, data, content_type):
    SENT["content_type"] = content_type
    SENT["data"] = data
    return tgupload.classify(content_type), "VID_FILE_ID_19"

tgupload.upload_media = fake_upload

async def fake_country(raw_ip):
    return "Bangladesh"

geoip.lookup_country = fake_country

from fastapi.testclient import TestClient
import app.main as main_mod
from app.main import app
from app.db import SessionLocal
from app import models, notify

# Phase 19.1: transcoding finishes as a background job. Collect the
# jobs instead of scheduling them, then drain them deterministically;
# bot notifications are recorded, not sent.
JOBS = []
NOTES = []

def collect_job(coro):
    JOBS.append(coro)

main_mod._schedule_video_job = collect_job

async def fake_send(chat_id, text):
    NOTES.append((chat_id, text))
    return True

notify.send_message = fake_send

import asyncio

_DRAIN_LOOP = None

def drain_jobs():
    # One persistent loop for every drain: asyncio primitives inside
    # the jobs (the transcode semaphore) bind to the first loop that
    # runs them, and gather() needs the jobs on ITS loop.
    global _DRAIN_LOOP
    jobs, JOBS[:] = JOBS[:], []
    if not jobs:
        return
    if _DRAIN_LOOP is None or _DRAIN_LOOP.is_closed():
        _DRAIN_LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_DRAIN_LOOP)
    _DRAIN_LOOP.run_until_complete(asyncio.gather(*jobs))


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, **extra):
    return {"X-Init-Data": make_init_data(
        {"id": uid, "first_name": name, **extra})}


OWNER = H(777, "Owner")
RAFI = H(555, "Rafi", language_code="bn")

# --- tiny real videos, generated with the local ffmpeg -------------------
FF = shutil.which("ffmpeg")
assert FF, "ffmpeg required for phase-19 tests"
os.makedirs("/tmp/p19", exist_ok=True)

def gen(name, args):
    path = f"/tmp/p19/{name}"
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=duration=2:size=320x240:rate=15",
                    *args, path], check=True)
    return path

MP4 = gen("tiny.mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p"])
MOV = gen("tiny.mov", ["-c:v", "libx264", "-pix_fmt", "yuv420p"])
WEBM = gen("tiny.webm", ["-c:v", "libvpx-vp9", "-b:v", "200k"])

with TestClient(app) as c:
    c.post("/auth", json={"initData": OWNER["X-Init-Data"]})

    # --- small MP4: fast path, bytes pass through untouched ----------
    raw = open(MP4, "rb").read()
    r = c.post("/posts/upload", headers=RAFI, data={"caption": "mp4"},
               files={"file": ("tiny.mp4", raw, "video/mp4")})
    assert r.status_code == 200 and r.json()["type"] == "video", r.text
    assert SENT["content_type"] == "video/mp4" and SENT["data"] == raw
    print("small MP4 fast path OK")

    # --- MOV: accepted (202), transcoded by the background job --------
    r = c.post("/posts/upload", headers=RAFI, data={"caption": "mov"},
               files={"file": ("tiny.mov", open(MOV, "rb").read(),
                               "video/quicktime")})
    assert r.status_code == 202 and r.json()["status"] == "processing", r.text
    assert len(JOBS) == 1
    drain_jobs()
    assert SENT["content_type"] == "video/mp4"
    assert SENT["data"][4:8] == b"ftyp", SENT["data"][:12]
    assert any("now live" in t for uid, t in NOTES if uid == 555), NOTES
    print("MOV transcoded to MP4 (background) OK")

    # --- WebM: same background treatment --------------------------------
    r = c.post("/posts/upload", headers=RAFI, data={"caption": "webm"},
               files={"file": ("tiny.webm", open(WEBM, "rb").read(),
                               "video/webm")})
    assert r.status_code == 202, r.text
    drain_jobs()
    assert SENT["data"][4:8] == b"ftyp"
    print("WebM transcoded to MP4 (background) OK")

    # --- oversize MP4 (cap patched small) also goes to the job ---------
    old_max = tgupload.MAX_MEDIA_BYTES
    tgupload.MAX_MEDIA_BYTES = 10000
    try:
        r = c.post("/posts/upload", headers=RAFI, data={"caption": "big"},
                   files={"file": ("tiny.mp4", raw, "video/mp4")})
        assert r.status_code == 202, r.text
        drain_jobs()
        assert SENT["data"] != raw and SENT["data"][4:8] == b"ftyp"
    finally:
        tgupload.MAX_MEDIA_BYTES = old_max
    print("oversize MP4 background path OK")

    # --- raw cap + unsupported type -----------------------------------
    old_raw = tgupload.RAW_VIDEO_MAX_BYTES
    tgupload.RAW_VIDEO_MAX_BYTES = 10000
    try:
        r = c.post("/posts/upload", headers=RAFI, data={"caption": "x"},
                   files={"file": ("tiny.webm", open(WEBM, "rb").read(),
                                   "video/webm")})
        assert r.status_code == 400 and "too large" in r.json()["detail"], r.text
    finally:
        tgupload.RAW_VIDEO_MAX_BYTES = old_raw
    r = c.post("/posts/upload", headers=RAFI, data={"caption": "x"},
               files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400, r.status_code
    print("raw cap + type validation OK")

    # --- sign-in captures language + country --------------------------
    r = c.post("/auth", json={"initData": RAFI["X-Init-Data"]},
               headers={"x-forwarded-for": "103.25.1.1"})
    assert r.status_code == 200, r.text
    r = c.get("/admin/users/555", headers=OWNER)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["language_code"] == "bn", d
    assert d["country"] == "Bangladesh", d
    assert d["last_seen_at"], d
    print("country/language capture OK")

    # --- heartbeat: elapsed seconds accumulate; gaps start sessions ---
    r = c.post("/me/heartbeat", headers=RAFI)
    assert r.status_code == 200 and r.json()["sessions_today"] == 1, r.text
    db = SessionLocal()
    row = db.query(models.UserActivity).filter_by(user_id=555).first()
    row.last_beat_at = datetime.utcnow() - timedelta(seconds=30)
    db.commit(); db.close()
    r = c.post("/me/heartbeat", headers=RAFI)
    assert r.json()["seconds_today"] == 30, r.json()
    db = SessionLocal()
    row = db.query(models.UserActivity).filter_by(user_id=555).first()
    row.last_beat_at = datetime.utcnow() - timedelta(seconds=300)
    db.commit(); db.close()
    r = c.post("/me/heartbeat", headers=RAFI)
    assert r.json()["sessions_today"] == 2 and r.json()["seconds_today"] == 30, r.json()
    print("heartbeat time tracking OK")

    # --- ad impressions: counted once per burst ------------------------
    r = c.post("/ads/shown", headers=RAFI)
    assert r.json()["counted"] is True, r.json()
    r = c.post("/ads/shown", headers=RAFI)
    assert r.json()["counted"] is False, r.json()
    print("ad impression counting OK")

    # --- dashboard aggregates ------------------------------------------
    r = c.get("/admin/dashboard", headers=RAFI)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/dashboard", headers=OWNER)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_members"] >= 1 and d["new_today"] >= 1, d
    assert d["ads_total"] == 1 and d["ads_today"] == 1, d
    assert d["time_today_seconds"] == 30, d
    assert len(d["signups_14d"]) == 14 and len(d["active_14d"]) == 14, d
    assert any(x["name"] == "Bangladesh" for x in d["countries"]), d
    assert any(x["name"] == "bn" for x in d["languages"]), d
    assert d["top_time_today"] and d["top_time_today"][0]["seconds"] == 30, d
    print("dashboard aggregates OK")

    # --- member detail --------------------------------------------------
    r = c.get("/admin/users/555", headers=OWNER)
    d = r.json()
    assert d["seconds_total"] == 30 and d["seconds_today"] == 30, d
    assert d["sessions_today"] == 2 and d["active_days"] == 1, d
    assert d["ads_watched"] == 1 and d["posts"] == 4, d
    r = c.get("/admin/users/424242", headers=OWNER)
    assert r.status_code == 404, r.status_code
    r = c.get("/admin/users", headers=OWNER)
    row = next(u for u in r.json()["users"] if u["telegram_id"] == 555)
    assert row["country"] == "Bangladesh" and row["last_seen_at"], row
    print("member detail OK")

    # --- frontend wiring -------------------------------------------------
    js = open("webapp/app.js").read()
    for marker in ("/admin/dashboard", "apiFormProgress", "startHeartbeat",
                   "/ads/shown", "openUserDetail", "/me/heartbeat"):
        assert marker in js, marker
    html = open("webapp/index.html").read()
    assert 'accept="image/*,video/*"' in html and 'id="dash-tiles"' in html
    assert 'id="admin-user-detail"' in html
    css = open("webapp/style.css").read()
    assert ".bar-fill" in css and ".detail-grid" in css
    print("frontend wiring OK")

print("PHASE 19 ALL OK")
