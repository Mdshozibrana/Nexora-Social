"""Phase-4 tests: bot-path posting via the shared service, per-user posts,
the feed 'liked' flag, /auth bot_username, and the media proxy guard."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase4.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.db import SessionLocal
from app import models
from app.users import get_or_create_user
from app.services import register_post


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


ALICE = make_init_data({"id": 111, "first_name": "Alice", "username": "alice"})
BOB = make_init_data({"id": 222, "first_name": "Bob", "username": "bob"})

with TestClient(app) as c:
    r = c.post("/auth", json={"initData": ALICE}); assert r.status_code == 200
    assert r.json()["bot_username"] == "NexoraSocial_bot", r.json()
    print("auth carries bot_username OK")

    # Bob arrives via Alice's referral, then "sends a photo to the bot":
    # the bot handler path is exactly get_or_create_user + register_post.
    db = SessionLocal()
    bob, _ = get_or_create_user(db, {"id": 222, "first_name": "Bob",
                                     "username": "bob"}, referrer_id=111)
    post, is_first, qualified = register_post(
        db, bob, "photo", "FILEID123", "Sunset #First")
    assert is_first and qualified
    assert post.hashtags == "first"
    alice = db.get(models.User, 111)
    bob = db.get(models.User, 222)
    assert bob.points_balance == 5 and alice.points_balance == 20, (
        bob.points_balance, alice.points_balance)
    post2, is_first2, _ = register_post(db, bob, "text", None, "second")
    assert not is_first2
    db.close()
    print("bot-path register_post: first-post points + qualification OK")

    r = c.get("/users/222/posts", headers={"X-Init-Data": ALICE})
    assert r.status_code == 200
    mine = r.json()["posts"]
    assert len(mine) == 2 and mine[0]["caption"] == "second", mine
    assert mine[1]["media_file_id"] == "FILEID123"
    r = c.get("/users/111/posts", headers={"X-Init-Data": ALICE})
    assert r.json()["posts"] == []
    r = c.get("/users/999/posts", headers={"X-Init-Data": ALICE})
    assert r.status_code == 404
    print("per-user posts OK")

    pid = mine[1]["id"]
    r = c.post(f"/posts/{pid}/like", headers={"X-Init-Data": ALICE})
    assert r.json()["liked"] is True
    feed_a = c.get("/feed", headers={"X-Init-Data": ALICE}).json()["posts"]
    feed_b = c.get("/feed", headers={"X-Init-Data": BOB}).json()["posts"]
    pa = [p for p in feed_a if p["id"] == pid][0]
    pb = [p for p in feed_b if p["id"] == pid][0]
    assert pa["liked"] is True and pb["liked"] is False
    print("feed liked flag is per-viewer OK")

    saved = settings.BOT_TOKEN
    settings.BOT_TOKEN = ""
    try:
        r = c.get("/media/FILEID123")
        assert r.status_code == 503, r.status_code
    finally:
        settings.BOT_TOKEN = saved
    print("media proxy refuses cleanly without a token (503) OK")

print("PHASE-4 TESTS PASSED")
