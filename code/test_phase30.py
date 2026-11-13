"""Phase-30 tests: the video lifecycle fix (owner report: a video
kept playing after being scrolled past and after switching pages)
and the uniqueness polish layer. The client parts are verified
statically — the lifecycle contract lives in app.js — plus an API
smoke check that nothing else moved."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase30.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

# --- video lifecycle contract ---
assert "function pauseAllVideos" in JS
# One-at-a-time: a starting video pauses the rest.
assert 'addEventListener("play"' in JS and "pauseAllVideos(e.target)" in JS
# App hidden -> everything pauses.
assert "visibilitychange" in JS and "document.hidden" in JS
# Feed/profile videos are observed and pause when scrolled away.
assert "feedVidObserver" in JS and "feedVidObserver.observe(vid)" in JS
assert "en.isIntersecting" in JS
# Every view switch pauses everything (Phase 30 line in showView).
assert "Phase 30: no video may follow the member to another page." in JS
assert "pauseAllVideos();" in JS
# The old reels-only pause (which let feed videos follow the member
# around the app) is gone.
assert 'else document.querySelectorAll("#video-list video")' not in JS
# Reels autoplay machinery is untouched.
assert "reelObserver" in JS and "moveNavPill" in JS
print("video lifecycle contract OK")

# --- uniqueness polish layer ---
for marker in ("Phase 30", "auroraA", "auroraB", "cardIn", "pillGlow",
               "sheen", "heartPop", "prefers-reduced-motion"):
    assert marker in CSS, marker
# Phase 105: the clay base moved to warm cream + sky accent.
assert "#F6F1E7" in CSS and "#3E8FD0" in CSS
print("polish layer OK")


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


with TestClient(app) as c:
    d = make_init_data({"id": 700, "first_name": "Viewer"})
    h = {"X-Init-Data": d}
    r = c.post("/auth", json={"initData": d})
    assert r.status_code == 200, r.text
    r = c.post("/posts", headers=h,
               json={"type": "text", "caption": "phase30 smoke"})
    assert r.status_code == 200, r.text
    r = c.get("/feed", headers=h)
    assert r.status_code == 200 and r.json()["posts"], r.text
print("api smoke OK")

print("PHASE-30 TESTS PASSED")
