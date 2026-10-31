"""Phase-6 tests: daily tasks (check-in / follow 2 / comment 5, once per
day) and the monetization gate checklist + unlock."""
import hashlib, hmac, json, os, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase6.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}

CAROL, DAVE, ERIN = H(333, "Carol"), H(444, "Dave"), H(555, "Erin")

with TestClient(app) as c:
    for h in (CAROL, DAVE, ERIN):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200

    tasks = c.get("/me/tasks", headers=CAROL).json()["tasks"]
    by_key = {t["key"]: t for t in tasks}
    assert set(by_key) == {"checkin", "follow2", "comment5"}, by_key
    assert by_key["checkin"]["claimable"] is True
    assert by_key["follow2"]["progress"] == 0 and by_key["follow2"]["claimable"] is False
    assert by_key["comment5"]["target"] == 5
    print("task list + initial state OK")

    r = c.post("/me/tasks/follow2/claim", headers=CAROL)
    assert r.status_code == 400
    r = c.post("/me/tasks/nope/claim", headers=CAROL)
    assert r.status_code == 404
    r = c.post("/me/tasks/checkin/claim", headers=CAROL)
    assert r.json() == {"ok": True, "points_awarded": 10, "balance": 10}, r.json()
    r = c.post("/me/tasks/checkin/claim", headers=CAROL)
    assert r.status_code == 400, "second check-in claim must be refused"
    print("check-in: claim once, second claim refused OK")

    c.post("/users/444/follow", headers=CAROL)
    t = {x["key"]: x for x in c.get("/me/tasks", headers=CAROL).json()["tasks"]}
    assert t["follow2"]["progress"] == 1 and t["follow2"]["claimable"] is False
    c.post("/users/555/follow", headers=CAROL)
    r = c.post("/me/tasks/follow2/claim", headers=CAROL)
    assert r.json()["points_awarded"] == 20 and r.json()["balance"] == 30
    print("follow-2 task: progress counts, claim pays OK")

    post = c.post("/posts", headers=DAVE,
                  json={"type": "text", "caption": "Dave post"}).json()
    for i in range(4):
        c.post(f"/posts/{post['id']}/comments", headers=CAROL,
               json={"text": f"c{i}"})
    t = {x["key"]: x for x in c.get("/me/tasks", headers=CAROL).json()["tasks"]}
    assert t["comment5"]["progress"] == 4 and t["comment5"]["claimable"] is False
    c.post(f"/posts/{post['id']}/comments", headers=CAROL, json={"text": "c5"})
    r = c.post("/me/tasks/comment5/claim", headers=CAROL)
    assert r.json()["points_awarded"] == 20 and r.json()["balance"] == 50
    print("comment-5 task OK")

    mon = c.get("/me/monetization", headers=CAROL).json()
    assert mon["unlocked"] is False
    checks = {x["key"]: x for x in mon["checks"]}
    assert checks["followers"]["required"] == 100 and checks["followers"]["done"] is False
    assert checks["lifetime_points"]["current"] == 50
    print("monetization gate: locked with honest progress OK")

    db = SessionLocal()
    carol = db.get(models.User, 333)
    carol.created_at = datetime.utcnow() - timedelta(days=20)
    for i in range(100):
        db.add(models.Follow(follower_id=900000 + i, following_id=333))
    for i in range(25):
        db.add(models.Post(user_id=333, type="text", caption=f"bulk {i}"))
    db.add(models.PointsLedger(user_id=333, amount=450, reason="bonus"))
    db.commit()
    db.close()
    mon = c.get("/me/monetization", headers=CAROL).json()
    assert mon["unlocked"] is True, mon
    assert all(x["done"] for x in mon["checks"])
    print("monetization unlocks when every target is met OK")

print("PHASE-6 TESTS PASSED")
