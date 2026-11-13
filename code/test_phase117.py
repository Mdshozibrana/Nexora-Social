"""Phase-117 tests: blue tick — TWO conditions, either one qualifies
(owner, Nov 13) + profile photo viewer entrance animation.

- 50 QUALIFIED referrals (referred member has posted — the
  monetization gate's definition) OR 1,000 followers. Either one
  alone qualifies; 49 referrals + 999 followers does not; 50
  UNqualified referrals do not count.
- The request lands in the Admin Panel (with the applicant's
  referral count, so the admin sees which condition was met); the
  admin approves (blue tick granted) or rejects (may apply again).
- The photo viewer opens with a zoom + fade animation.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase117.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


UID = {"A": 771, "B": 772, "C": 773, "D": 774, "ADMIN": 999}
_next = [30000]


def _users(db, n):
    rows = []
    for _ in range(n):
        _next[0] += 1
        rows.append(models.User(telegram_id=_next[0],
                                first_name="F"))
    db.add_all(rows)
    db.flush()
    return [u.telegram_id for u in rows]


def add_followers(db, target, n):
    fids = _users(db, n)
    db.add_all(models.Follow(follower_id=f, following_id=target)
               for f in fids)


def add_referrals(db, referrer, n, qualified):
    rids = _users(db, n)
    db.add_all(models.Referral(referrer_id=referrer, new_user_id=r,
                               qualified=qualified) for r in rids)


with TestClient(app) as c:
    for name, uid in UID.items():
        r = c.post("/auth", json={"initData": H(uid, name)["X-Init-Data"]})
        assert r.status_code == 200, name
    db = SessionLocal()
    add_followers(db, UID["A"], 999)
    add_referrals(db, UID["A"], 49, True)
    add_referrals(db, UID["B"], 50, True)
    add_followers(db, UID["C"], 1000)
    add_referrals(db, UID["D"], 50, False)
    db.commit()
    db.close()

    # A: 49 referrals + 999 followers — NEITHER condition met.
    r = c.get("/me/verification", headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["followers"], v["referrals"]) == (999, 49), v
    assert v["met"] == [] and v["can_apply"] is False, v
    assert c.post("/me/verification/apply",
                  headers=H(UID["A"], "A")).status_code == 400
    print("A (49 refs + 999 followers): not eligible OK")

    # B: 50 qualified referrals, 0 followers — referrals qualify.
    r = c.get("/me/verification", headers=H(UID["B"], "B"))
    v = r.json()
    assert (v["followers"], v["referrals"]) == (0, 50), v
    assert v["met"] == ["referrals"] and v["can_apply"] is True, v
    r = c.post("/me/verification/apply", headers=H(UID["B"], "B"))
    assert r.status_code == 200, r.text
    assert c.get("/me/verification",
                 headers=H(UID["B"], "B")).json()["pending"] is True
    assert c.post("/me/verification/apply",
                  headers=H(UID["B"], "B")).status_code == 400
    print("B (50 qualified referrals): eligible + applied + no dup OK")

    # C: 1,000 followers, 0 referrals — followers qualify.
    r = c.get("/me/verification", headers=H(UID["C"], "C"))
    v = r.json()
    assert (v["followers"], v["referrals"]) == (1000, 0), v
    assert v["met"] == ["followers"] and v["can_apply"] is True, v
    assert c.post("/me/verification/apply",
                  headers=H(UID["C"], "C")).status_code == 200
    print("C (1,000 followers): eligible + applied OK")

    # D: 50 UNqualified referrals — they do not count.
    r = c.get("/me/verification", headers=H(UID["D"], "D"))
    v = r.json()
    assert (v["followers"], v["referrals"]) == (0, 0), v
    assert v["can_apply"] is False, v
    print("D (50 unqualified referrals): not eligible OK")

    # Admin Panel: the requests arrive with referral counts; the
    # admin approves B (blue tick granted) and rejects C (may
    # apply again).
    r = c.get("/admin/verifications", headers=H(UID["ADMIN"], "ADMIN"))
    assert r.status_code == 200, r.text
    reqs = {q["telegram_id"]: q for q in r.json()["requests"]}
    assert reqs[UID["B"]]["referrals"] == 50, reqs[UID["B"]]
    assert reqs[UID["B"]]["met"] == ["referrals"]
    assert reqs[UID["C"]]["followers"] == 1000
    assert r.json()["pending_count"] == 2
    r = c.post(f"/admin/verifications/{reqs[UID['B']]['id']}/decide",
               json={"approve": True}, headers=H(UID["ADMIN"], "ADMIN"))
    assert r.status_code == 200 and r.json()["is_verified"] is True
    v = c.get("/me/verification", headers=H(UID["B"], "B")).json()
    assert v["is_verified"] is True and v["can_apply"] is False
    r = c.post(f"/admin/verifications/{reqs[UID['C']]['id']}/decide",
               json={"approve": False}, headers=H(UID["ADMIN"], "ADMIN"))
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    v = c.get("/me/verification", headers=H(UID["C"], "C")).json()
    assert v["last_status"] == "rejected" and v["can_apply"] is True
    print("admin: approve grants the tick, reject lets them re-apply OK")

    # Client: two-condition card, admin referrals, viewer animation.
    html = c.get("/webapp/").text
    js = c.get("/webapp/app.js").text
    css = c.get("/webapp/style.css").text
    for bit in ("Referrals for the blue tick",
                "Either one qualifies",
                "with 50 referrals",
                "with 1,000 followers",
                "q.referrals + \" referrals",
                "50 referrals."):
        assert bit in js, bit
    for bit in ("@keyframes pvZoomIn", "@keyframes pvFadeIn",
                "#pv-img { animation: pvZoomIn",
                "#photo-viewer { animation: pvFadeIn"):
        assert bit in css, bit
    for asset in ("style.css?v=118", "app.js?v=118", "games.js?v=118"):
        assert asset in html, asset
    for bit in ("maybeLoadMoreDesigns", "loadRelatedDesigns",
                "loadMyQr", "showTaskAd", "openPhotoViewer"):
        assert bit in js, bit
    print("client: two-condition card + admin referrals + viewer anim OK")

print("PHASE 117 OK")
