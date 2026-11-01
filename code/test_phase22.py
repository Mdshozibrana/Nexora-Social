"""Phase-22 tests: blue-tick verification applications (owner rule:
1,000 followers to apply). Covers the member side (status card data,
the follower gate at exactly 999 vs 1,000, one pending application
at a time, re-apply after rejection, no applying once verified) and
the admin side (403 for members, the review list with applicant
stats, approve grants users.is_verified everywhere, reject does
not, decided applications cannot be re-decided, and the applicant
is notified in-app both ways).
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase22.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import notify

async def fake_send(chat_id, text):
    return True

notify.send_message = fake_send

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models


def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())), "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


OWNER = H(777, "Owner")
A = H(601, "Ayesha")
B = H(602, "Bilal")


def add_fans(target_id, start, count):
    db = SessionLocal()
    for i in range(start, start + count):
        fid = 9000001000 + i
        db.add(models.User(telegram_id=fid, first_name=f"Fan {i}"))
        db.add(models.Follow(follower_id=fid, following_id=target_id))
    db.commit()
    db.close()


with TestClient(app) as c:
    for h in (OWNER, A, B):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # --- the gate: 0 and 999 followers cannot apply ----------------------
    r = c.get("/me/verification", headers=A)
    d = r.json()
    assert d["followers"] == 0 and d["required"] == 1000, d
    assert d["can_apply"] is False and d["is_verified"] is False, d
    r = c.post("/me/verification/apply", headers=A)
    assert r.status_code == 400, r.status_code
    add_fans(601, 0, 999)
    r = c.get("/me/verification", headers=A)
    assert r.json()["followers"] == 999, r.json()
    r = c.post("/me/verification/apply", headers=A)
    assert r.status_code == 400, r.status_code
    add_fans(601, 999, 1)
    r = c.get("/me/verification", headers=A)
    assert r.json()["followers"] == 1000, r.json()
    assert r.json()["can_apply"] is True, r.json()
    print("follower gate OK (999 no, 1000 yes)")

    # --- apply once; a second pending application is refused --------------
    r = c.post("/me/verification/apply", headers=A)
    assert r.status_code == 200, r.text
    r = c.post("/me/verification/apply", headers=A)
    assert r.status_code == 400, r.status_code
    r = c.get("/me/verification", headers=A)
    assert r.json()["pending"] is True, r.json()

    # --- admin review: members shut out, owner sees the application -------
    r = c.get("/admin/verifications", headers=B)
    assert r.status_code == 403, r.status_code
    r = c.post("/admin/verifications/1/decide", headers=B,
               json={"approve": True})
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/verifications", headers=OWNER)
    d = r.json()
    assert d["pending_count"] == 1, d
    app_row = d["requests"][0]
    assert app_row["telegram_id"] == 601, app_row
    assert app_row["followers"] == 1000, app_row
    assert app_row["status"] == "pending", app_row
    req_id = app_row["id"]

    # --- rejection: no tick, applicant notified, re-apply allowed ---------
    r = c.post(f"/admin/verifications/{req_id}/decide", headers=OWNER,
               json={"approve": False})
    assert r.status_code == 200, r.text
    assert r.json()["is_verified"] is False, r.json()
    r = c.get("/users/601", headers=B)
    assert r.json()["is_verified"] is False, r.json()
    r = c.get("/me/verification", headers=A)
    assert r.json()["last_status"] == "rejected", r.json()
    assert r.json()["can_apply"] is True, r.json()
    r = c.get("/me/notifications", headers=A)
    assert any(n["type"] == "verification"
               for n in r.json()["notifications"]), r.json()
    r = c.post(f"/admin/verifications/{req_id}/decide", headers=OWNER,
               json={"approve": True})
    assert r.status_code == 400, r.status_code  # already decided

    # --- approval: the tick goes live everywhere ---------------------------
    r = c.post("/me/verification/apply", headers=A)
    assert r.status_code == 200, r.text
    r = c.get("/admin/verifications", headers=OWNER)
    req2 = [q for q in r.json()["requests"]
            if q["status"] == "pending"][0]
    r = c.post(f"/admin/verifications/{req2['id']}/decide", headers=OWNER,
               json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_verified"] is True, r.json()
    r = c.get("/users/601", headers=B)
    assert r.json()["is_verified"] is True, r.json()
    r = c.get("/me/verification", headers=A)
    assert r.json()["is_verified"] is True, r.json()
    r = c.get("/me/notifications", headers=A)
    texts = [n["text"] for n in r.json()["notifications"]
             if n["type"] == "verification"]
    assert any("approved" in t for t in texts), texts
    r = c.post("/me/verification/apply", headers=A)
    assert r.status_code == 400, r.status_code  # already verified
    print("apply / reject / re-apply / approve flow OK")

    # --- frontend wiring ------------------------------------------------------
    html = open("webapp/index.html").read()
    js = open("webapp/app.js").read()
    assert 'id="admin-verifications"' in html
    for marker in ("loadVerifications", "decideVerification",
                   "Apply for the Blue Tick", "/me/verification"):
        assert marker in js, marker
    print("frontend wiring OK")

print("PHASE 22 ALL OK")
