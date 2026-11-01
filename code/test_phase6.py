"""Phase-6 tests: daily tasks (check-in 20 / follow-2 5 / comment-5 5,
once per day), the 30-day unbroken check-in streak, and the monetization
gate (followers 500, posts 25, age 14d, lifetime points 5000, streak 30).
Numbers per the owner's update, Oct 31."""
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
    params = {"auth_date": str(int(__import__("time").time())), "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}

CAROL, DAVE, ERIN = H(333, "Carol"), H(444, "Dave"), H(555, "Erin")
TODAY = datetime.utcnow().date()

with TestClient(app) as c:
    for h in (CAROL, DAVE, ERIN):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200

    tasks = c.get("/me/tasks", headers=CAROL).json()["tasks"]
    by_key = {t["key"]: t for t in tasks}
    assert set(by_key) == {"checkin", "follow2", "comment5"}, by_key
    assert by_key["checkin"]["points"] == 20 and by_key["checkin"]["claimable"] is True
    assert by_key["follow2"]["points"] == 5 and by_key["comment5"]["points"] == 5
    assert by_key["checkin"]["streak"] == 0
    print("task list + owner point values OK")

    r = c.post("/me/tasks/follow2/claim", headers=CAROL)
    assert r.status_code == 400
    r = c.post("/me/tasks/nope/claim", headers=CAROL)
    assert r.status_code == 404
    r = c.post("/me/tasks/checkin/claim", headers=CAROL)
    assert r.json() == {"ok": True, "points_awarded": 20, "balance": 20}, r.json()
    r = c.post("/me/tasks/checkin/claim", headers=CAROL)
    assert r.status_code == 400, "second check-in claim must be refused"
    t = {x["key"]: x for x in c.get("/me/tasks", headers=CAROL).json()["tasks"]}
    assert t["checkin"]["streak"] == 1
    print("check-in: +20 once, second claim refused, streak 1 OK")

    c.post("/users/444/follow", headers=CAROL)
    c.post("/users/555/follow", headers=CAROL)
    r = c.post("/me/tasks/follow2/claim", headers=CAROL)
    assert r.json()["points_awarded"] == 5 and r.json()["balance"] == 25
    post = c.post("/posts", headers=DAVE,
                  json={"type": "text", "caption": "Dave post"}).json()
    for i in range(5):
        c.post(f"/posts/{post['id']}/comments", headers=CAROL,
               json={"text": f"c{i}"})
    r = c.post("/me/tasks/comment5/claim", headers=CAROL)
    assert r.json()["points_awarded"] == 5 and r.json()["balance"] == 30
    print("follow-2 (+5) and comment-5 (+5) tasks OK")

    mon = c.get("/me/monetization", headers=CAROL).json()
    assert mon["unlocked"] is False
    checks = {x["key"]: x for x in mon["checks"]}
    assert checks["followers"]["required"] == 500
    assert checks["lifetime_points"]["required"] == 5000
    assert checks["lifetime_points"]["current"] == 30
    assert checks["checkin_streak"]["required"] == 30
    assert checks["checkin_streak"]["current"] == 1
    print("monetization gate: owner targets, locked state OK")

    # Streak rules: a gap kills it; yesterday-ending streak stays alive.
    db = SessionLocal()
    for back in range(2, 7):  # Dave: 5 days ending 2 days ago (gap yesterday)
        db.add(models.DailyClaim(user_id=444, task_key="checkin",
                                 day=(TODAY - timedelta(days=back)).isoformat()))
    for back in (1, 2):       # Erin: yesterday + day before, none today
        db.add(models.DailyClaim(user_id=555, task_key="checkin",
                                 day=(TODAY - timedelta(days=back)).isoformat()))
    db.commit()
    mon_d = c.get("/me/monetization", headers=DAVE).json()
    streak_d = {x["key"]: x for x in mon_d["checks"]}["checkin_streak"]["current"]
    assert streak_d == 0, streak_d
    t_e = {x["key"]: x for x in c.get("/me/tasks", headers=ERIN).json()["tasks"]}
    assert t_e["checkin"]["streak"] == 2, t_e["checkin"]
    print("streak: missed day breaks it, yesterday-ending streak alive OK")

    # Unlock Carol: age, 500 followers, 25 posts, 5000 lifetime, 30-day streak.
    carol = db.get(models.User, 333)
    carol.created_at = datetime.utcnow() - timedelta(days=20)
    for i in range(500):
        db.add(models.Follow(follower_id=900000 + i, following_id=333))
    for i in range(25):
        db.add(models.Post(user_id=333, type="text", caption=f"bulk {i}"))
    db.add(models.PointsLedger(user_id=333, amount=4970, reason="bonus"))
    for back in range(1, 30):  # today already claimed -> streak 30 total
        db.add(models.DailyClaim(user_id=333, task_key="checkin",
                                 day=(TODAY - timedelta(days=back)).isoformat()))
    db.commit()
    db.close()
    mon = c.get("/me/monetization", headers=CAROL).json()
    assert mon["unlocked"] is True, mon
    assert all(x["done"] for x in mon["checks"])
    print("monetization unlocks when every target incl. 30-day streak is met OK")

print("PHASE-6 TESTS PASSED")
