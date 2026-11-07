"""Phase-38 tests: speed & smoothness (owner request). Covers
gzip on API JSON and webapp assets, the versioned-asset cache
policy (assets cache hard, the shell never does), and that the
batched view-count queries still return exact numbers."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase38.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

HTML = open("webapp/index.html").read()
# Phase 39 bumped the asset version to ?v=39 (the pin
# here is that assets ARE versioned, not the number).
assert "app.js?v=99" in HTML and "style.css?v=99" in HTML
assert "games.js?v=99" in HTML
print("versioned assets OK")


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
    # --- asset policy: shell revalidates, versioned assets cache ---
    r = c.get("/webapp/")
    assert r.status_code == 200, r.status_code
    assert "no-cache" in r.headers.get("cache-control", ""), \
        r.headers.get("cache-control")
    r = c.get("/webapp/app.js?v=99")
    assert r.status_code == 200, r.status_code
    cc = r.headers.get("cache-control", "")
    assert "max-age=604800" in cc, cc
    # --- gzip on the big asset (httpx decodes; the header proves it)
    assert r.headers.get("content-encoding") == "gzip", r.headers
    assert b"paintDesignAccess" in r.content
    r = c.get("/webapp/style.css?v=99")
    assert r.headers.get("content-encoding") == "gzip", r.headers
    print("cache + gzip on assets OK")

    for h in (A, B):
        c.post("/auth", json={"initData": h["X-Init-Data"]})
    for i in range(6):
        c.post("/posts", headers=A, json={
            "type": "text", "caption": "status number %d" % i})
    rv = c.post("/posts", headers=A, json={
        "type": "video", "media_file_id": "vd38", "caption": "clip"})
    vid = rv.json()["id"]
    c.post(f"/posts/{vid}/view", headers=B)

    # --- gzip on API JSON ---
    r = c.get("/feed", headers=B)
    assert r.headers.get("content-encoding") == "gzip", r.headers
    posts = r.json()["posts"]
    assert len(posts) >= 6, len(posts)
    assert all("views" in p for p in posts)

    # --- batched counts are exact ---
    vids = c.get("/feed?type=video", headers=B).json()["posts"]
    mine = [p for p in vids if p["id"] == vid]
    assert len(mine) == 1 and mine[0]["views"] == 1, vids
    prof = c.get("/users/880/posts", headers=B).json()["posts"]
    mine = [p for p in prof if p["id"] == vid]
    assert len(mine) == 1 and mine[0]["views"] == 1, prof
    print("gzip on API + exact batched counts OK")

print("PHASE-38 TESTS PASSED")
