"""Phase-9 tests: Save/bookmark behind the reels options menu — toggle,
per-viewer saved flag in feeds, /me/saved listing, deleted posts drop out."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase9.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())), "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}

ANN, BEN = H(101, "Ann"), H(202, "Ben")

with TestClient(app) as c:
    for h in (ANN, BEN):
        assert c.post("/auth", json={"initData": h["X-Init-Data"]}).status_code == 200

    post = c.post("/posts", headers=ANN, json={
        "type": "video", "media_file_id": "VID9", "caption": "Ann reel"}).json()

    r = c.post(f"/posts/{post['id']}/save", headers=BEN)
    assert r.json() == {"saved": True, "post_id": post["id"]}, r.json()
    feed_ben = c.get("/feed?type=video", headers=BEN).json()["posts"]
    assert [p["saved"] for p in feed_ben if p["id"] == post["id"]] == [True]
    feed_ann = c.get("/feed?type=video", headers=ANN).json()["posts"]
    assert [p["saved"] for p in feed_ann if p["id"] == post["id"]] == [False]
    saved = c.get("/me/saved", headers=BEN).json()["posts"]
    assert len(saved) == 1 and saved[0]["id"] == post["id"] and saved[0]["saved"] is True
    assert c.get("/me/saved", headers=ANN).json()["posts"] == []
    print("save toggle + per-viewer flag + /me/saved OK")

    r = c.post(f"/posts/{post['id']}/save", headers=BEN)
    assert r.json()["saved"] is False
    assert c.get("/me/saved", headers=BEN).json()["posts"] == []
    print("unsave removes it OK")

    c.post(f"/posts/{post['id']}/save", headers=BEN)
    c.delete(f"/posts/{post['id']}", headers=ANN)
    assert c.get("/me/saved", headers=BEN).json()["posts"] == []
    r = c.post(f"/posts/{post['id']}/save", headers=BEN)
    assert r.status_code == 404
    r = c.post("/posts/99999/save", headers=BEN)
    assert r.status_code == 404
    print("deleted/missing posts cannot stay saved OK")

print("PHASE-9 TESTS PASSED")
