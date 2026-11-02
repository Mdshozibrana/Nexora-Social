"""Phase-44 tests: the Earning Panel (owner's spec). Real data
only for impressions + points; money = impressions x the owner-
set rate (estimate). Covers admin-only access, the counts
(today / month / total / 14-day series), the rate save + the
estimate math, and both top-points lists."""
import hashlib, hmac, json, os, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase44.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
for marker in ('class="earn-panel"', 'id="earn-ads-today"',
               'id="earn-est-month"', 'id="earn-rate-in"',
               'id="earn-chart"', 'id="earn-top-points"',
               'id="earn-top-today"', "?v=54"):
    assert marker in HTML, marker
for marker in ("loadEarnings", "/admin/earnings", "fmtTk"):
    assert marker in JS, marker
assert ".earn-panel" in CSS and ".earn-col-bar" in CSS
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


OWNER = H(999, "Owner")
A = H(880, "Alice")
B = H(881, "Bob")

with TestClient(app) as c:
    for h in (OWNER, A, B):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # members cannot see the panel's data or set the rate
    assert c.get("/admin/earnings", headers=A).status_code == 403
    assert c.post("/admin/earnings/rate", headers=A,
                  json={"rate_per_1000": 100}).status_code == 403

    # seed: Alice rich in points, Bob earned more today; ad views
    # today x3, one 40 days ago (outside this month window check
    # is relative to 'now', so 40 days ago is last month for sure
    # only if today is not the 1st-9th... use 70 days to be safe)
    db = SessionLocal()
    now = datetime.utcnow()
    ua = db.get(models.User, 880)
    ua.points_balance = 900
    ub = db.get(models.User, 881)
    ub.points_balance = 300
    for _ in range(3):
        db.add(models.AdEvent(user_id=880, created_at=now))
    db.add(models.AdEvent(user_id=881,
                           created_at=now - timedelta(days=70)))
    db.add(models.PointsLedger(user_id=880, amount=20,
                               reason="checkin", created_at=now))
    db.add(models.PointsLedger(user_id=881, amount=45,
                               reason="post", created_at=now))
    db.add(models.PointsLedger(user_id=881, amount=-10,
                               reason="spend", created_at=now))
    db.commit()
    db.close()

    r = c.get("/admin/earnings", headers=OWNER)
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["ads_today"] == 3 and e["ads_total"] == 4, e
    assert e["ads_month"] == 3, e  # the 70-day-old one is excluded
    assert e["rate_per_1000"] == 0 and e["est_today"] == 0, e
    assert len(e["daily_14d"]) == 14 and e["daily_14d"][-1]["ads"] == 3, e
    assert e["top_points"][0]["telegram_id"] == 880 and \
        e["top_points"][0]["points"] == 900, e["top_points"]
    # today's earners: Bob +45 (the -10 spend never counts), Alice +20
    assert e["top_earners_today"][0]["telegram_id"] == 881 and \
        e["top_earners_today"][0]["earned"] == 45, e["top_earners_today"]
    print("earnings data OK")

    # the rate: 250 BDT per 1000 ads -> today 3 ads = 0.75
    r = c.post("/admin/earnings/rate", headers=OWNER,
               json={"rate_per_1000": 250})
    assert r.status_code == 200, r.text
    e = c.get("/admin/earnings", headers=OWNER).json()
    assert e["rate_per_1000"] == 250 and e["rate_per_ad"] == 0.25, e
    assert e["est_today"] == 0.75 and e["est_month"] == 0.75, e
    r = c.post("/admin/earnings/rate", headers=OWNER,
               json={"rate_per_1000": -5})
    assert r.status_code == 422, r.status_code
    print("rate + estimate math OK")

print("PHASE-44 TESTS PASSED")
