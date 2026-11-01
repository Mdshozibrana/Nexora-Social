"""Phase-7 tests: Videos page feed filter (type=video, Explore/Following)
and the Leaderboard endpoint (order, ranks, my-rank outside the top 50)."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase7.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models


def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())), "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}

ANN, BEN, CY = H(101, "Ann"), H(202, "Ben"), H(303, "Cy")

with TestClient(app) as c:
    for h in (ANN, BEN, CY):
        assert c.post("/auth", json={"initData": h["X-Init-Data"]}).status_code == 200

    c.post("/posts", headers=ANN, json={"type": "text", "caption": "Ann text"})
    c.post("/posts", headers=ANN, json={"type": "video", "media_file_id": "VID1",
                                        "caption": "Ann video #travel"})
    c.post("/posts", headers=BEN, json={"type": "photo", "media_file_id": "IMG1",
                                        "caption": "Ben photo"})
    c.post("/posts", headers=BEN, json={"type": "video", "media_file_id": "VID2",
                                        "caption": "Ben video"})

    vids = c.get("/feed?type=video", headers=CY).json()["posts"]
    assert len(vids) == 2 and all(p["type"] == "video" for p in vids), vids
    photos = c.get("/feed?type=photo", headers=CY).json()["posts"]
    assert len(photos) == 1 and photos[0]["media_file_id"] == "IMG1"
    allp = c.get("/feed", headers=CY).json()["posts"]
    # Phase 35: the Feed page shows statuses + photos only (Ann's
    # text, Ben's photo, the official welcome) — videos moved to
    # the Videos page source asserted above.
    assert len(allp) == 3, allp
    print("feed type filter (Videos page source) OK")

    c.post("/users/101/follow", headers=CY)
    fv = c.get("/feed?type=video&tab=following", headers=CY).json()["posts"]
    assert len(fv) == 1 and fv[0]["media_file_id"] == "VID1", fv
    print("videos Following tab shows only followed creators OK")

    db = SessionLocal()
    for uid, bal in ((101, 300), (202, 900), (303, 50)):
        u = db.get(models.User, uid)
        u.points_balance = bal
    for i in range(55):
        db.add(models.User(telegram_id=10000 + i, first_name=f"Bulk{i}",
                           points_balance=2000 + i))
    db.commit()
    db.close()

    board = c.get("/leaderboard", headers=CY).json()
    leaders = board["leaders"]
    assert len(leaders) == 50
    assert leaders[0]["points"] == 2054 and leaders[0]["rank"] == 1
    pts = [r["points"] for r in leaders]
    assert pts == sorted(pts, reverse=True)
    assert board["me"]["telegram_id"] == 303 and board["me"]["rank"] == 58, board["me"]
    board_ben = c.get("/leaderboard", headers=BEN).json()
    assert board_ben["me"]["rank"] == 56  # 55 bulk users above 900
    print("leaderboard order + my-rank (incl. outside top 50) OK")

print("PHASE-7 TESTS PASSED")
