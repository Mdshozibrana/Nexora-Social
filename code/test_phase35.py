"""Phase-35 tests: content routing (owner directive: user videos
show on the Videos page; statuses and images show on the Feed
page) and the wordmark contrast fix (owner: the 'Nexora Social'
text blended into the app background)."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase35.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

CSS = open("webapp/style.css").read()
JS = open("webapp/app.js").read()

# --- wordmark: deep, readable tones on the light clay hero ---
assert "Phase 35" in CSS and "#app-name { color: #472A3E; }" in CSS
assert "#D81B60" in CSS  # rich rose-violet gradient replaces white
# --- wording: a finished video is announced as live in Videos ---
assert "live in Videos" in JS
print("client contract OK")


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid,
                                           "first_name": name})}


A = H(880, "Poster")
B = H(881, "Reader")

with TestClient(app) as c:
    for h in (A, B):
        c.post("/auth", json={"initData": h["X-Init-Data"]})
    c.post("/posts", headers=A, json={"type": "text",
                                      "caption": "a status"})
    c.post("/posts", headers=A, json={"type": "photo",
                                      "media_file_id": "ph1",
                                      "caption": "a photo"})
    rv = c.post("/posts", headers=A, json={"type": "video",
                                           "media_file_id": "vd1",
                                           "caption": "a video"})
    vid_id = rv.json()["id"]

    # Feed page source: statuses + photos, NO videos. (The seeded
    # official welcome post is a text post and belongs here too.)
    feed = c.get("/feed", headers=B).json()["posts"]
    assert all(p["type"] != "video" for p in feed), feed
    assert all(p["id"] != vid_id for p in feed)
    mine = [p for p in feed if p["author_id"] == 880]
    assert sorted(p["type"] for p in mine) == ["photo", "text"], mine

    # Videos page source (what loadVideos asks for): videos only.
    vids = c.get("/feed?type=video", headers=B).json()["posts"]
    assert len(vids) == 1 and vids[0]["id"] == vid_id, vids

    # Explicit photo/text filters still work.
    photos = c.get("/feed?type=photo", headers=B).json()["posts"]
    assert len(photos) == 1 and photos[0]["type"] == "photo", photos

    # Following tab obeys the same split. (B also auto-follows the
    # official account, whose welcome post is a text post — filter
    # to A's own posts for the type check.)
    c.post("/users/880/follow", headers=B)
    fol = c.get("/feed?tab=following", headers=B).json()["posts"]
    assert all(p["type"] != "video" for p in fol), fol
    fol_mine = [p for p in fol if p["author_id"] == 880]
    assert sorted(p["type"] for p in fol_mine) == ["photo", "text"], \
        fol_mine
    folv = c.get("/feed?tab=following&type=video",
                 headers=B).json()["posts"]
    assert len(folv) == 1 and folv[0]["type"] == "video", folv

    # The profile still shows ALL of the member's posts (it is
    # their own page, not the Feed).
    prof = c.get("/users/880/posts", headers=B).json()["posts"]
    assert vid_id in [p["id"] for p in prof], prof
    print("feed/videos split OK")

print("PHASE-35 TESTS PASSED")
