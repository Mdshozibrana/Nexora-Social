"""Phase-8 tests: the official "Nexora Social" account — verified mark,
mandatory auto-follow for every member, unfollow blocked, and the
10,000 starting-follower display base."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase8.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}

ZOE, YAN = H(888, "Zoe"), H(889, "Yan")

with TestClient(app) as c:
    for h in (ZOE, YAN):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200
        assert r.json()["is_verified"] is False

    off = c.get("/users/1", headers=ZOE).json()
    assert off["first_name"] == "Nexora Social", off
    assert off["username"] == "nexora"
    assert off["is_verified"] is True and off["is_official"] is True
    assert off["following"] is True, "new user must auto-follow the official account"
    assert off["followers"] == 10002, off["followers"]  # 10,000 base + Zoe + Yan
    print("official account: verified, auto-followed, 10k base OK")

    feed = c.get("/feed", headers=ZOE).json()["posts"]
    welcome = [p for p in feed if p["author_id"] == 1]
    assert len(welcome) == 1 and welcome[0]["author_verified"] is True
    assert welcome[0]["caption"].startswith("Welcome to Nexora")
    fol = c.get("/feed?tab=following", headers=ZOE).json()["posts"]
    assert any(p["author_id"] == 1 for p in fol)
    print("welcome post in Explore + Following feeds, verified badge data OK")

    r = c.post("/users/1/follow", headers=ZOE)
    assert r.status_code == 400, "unfollowing the official account must fail"
    off2 = c.get("/users/1", headers=ZOE).json()
    assert off2["following"] is True
    print("official account cannot be unfollowed OK")

    res = c.get("/search?q=Nexora", headers=YAN).json()["users"]
    assert res and res[0]["telegram_id"] == 1 and res[0]["is_verified"] is True
    board = c.get("/leaderboard", headers=YAN).json()["leaders"]
    offrow = [r for r in board if r["telegram_id"] == 1]
    assert offrow and offrow[0]["is_verified"] is True
    print("verified flag in search + leaderboard OK")

print("PHASE-8 TESTS PASSED")
