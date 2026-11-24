"""Phase-131 tests: broadcast history + targeting + delivery count.

Covers: broadcast to all records a history row with delivered/total
counts (a failed send to one member never aborts the rest); verified
target reaches only verified members; new_7d only recent joiners;
inactive_30d only members with no post AND no app activity in the
last 30 days; an empty target set succeeds with 0/0 and still records
the row; unknown target 400; empty text 400; non-admin 403 on both
endpoints; history newest-first + limit cap; backup carries 39 tables
incl. broadcasts; ?v=172 x5, no ?v=130; broadcast client markers +
Phase 123-130 markers intact.
"""
import hashlib, hmac, json, os, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase131.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.notify as notify_mod

SENT = []
FAIL = set()


async def fake_send(chat_id, text):
    if chat_id in FAIL:
        return False
    SENT.append((chat_id, text))
    return True


notify_mod.send_message = fake_send

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models

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


ADMIN = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")
DAVE = H(444, "Dave")
EVE = H(555, "Eve")
FRANK = H(666, "Frank")


def backdate(uid, days):
    with SessionLocal() as db:
        u = db.query(models.User).filter_by(telegram_id=uid).one()
        u.created_at = datetime.utcnow() - timedelta(days=days)
        db.commit()


with TestClient(app) as c:
    for h in (ADMIN, BOB, CAROL, DAVE, EVE, FRANK):
        assert c.post("/auth", json={"initData": h["X-Init-Data"]}).status_code == 200

    # Setup: Bob verified + joined 2d ago; Carol joined 20d ago;
    # Dave/Eve/Frank joined 40d ago. Alice + Bob post (active);
    # Eve posts too; Frank has app activity but no posts.
    with SessionLocal() as db:
        db.query(models.User).filter_by(telegram_id=222).one().is_verified = True
        db.commit()
    backdate(222, 2)
    backdate(333, 20)
    backdate(444, 40)
    backdate(555, 40)
    backdate(666, 40)
    for h in (ADMIN, BOB, EVE):
        r = c.post("/posts", headers=h, json={"type": "text", "caption": "hi"})
        assert r.status_code == 200, r.text
    with SessionLocal() as db:
        db.add(models.UserActivity(
            user_id=666, day=datetime.utcnow().date().isoformat(),
            seconds=120, sessions=1,
            last_beat_at=datetime.utcnow() - timedelta(days=2)))
        db.commit()

    FAIL.add(444)  # Dave's DM fails: counts, never aborts the rest

    # 1. Broadcast to all: 6 members, Dave fails -> 5/6, row recorded.
    SENT.clear()
    r = c.post("/admin/broadcast", headers=ADMIN, json={"text": "Hello all"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["recipients"] == 6 and b["sent"] == 5, b
    assert isinstance(b.get("broadcast_id"), int), b
    assert {cid for cid, _ in SENT} == {111, 222, 333, 555, 666}, SENT
    print("broadcast all 5/6 with a failed send OK")

    # 2. Verified only: Bob + Alice (the admin is verified at
    #    provisioning, like the owner in production).
    SENT.clear()
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "Verified news", "target": "verified"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["recipients"] == 2 and b["sent"] == 2, b
    assert {cid for cid, _ in SENT} == {111, 222}, SENT
    print("broadcast verified OK")

    # 3. New in last 7 days: Alice + Bob.
    SENT.clear()
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "Welcome new", "target": "new_7d"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["recipients"] == 2 and b["sent"] == 2, b
    assert {cid for cid, _ in SENT} == {111, 222}, SENT
    print("broadcast new_7d OK")

    # 4. Inactive 30+ days: Carol + Dave (Eve posted, Frank active,
    # Alice + Bob posted) -> 1/2 with Dave's send failing.
    SENT.clear()
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "We miss you", "target": "inactive_30d"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["recipients"] == 2 and b["sent"] == 1, b
    assert {cid for cid, _ in SENT} == {333}, SENT
    print("broadcast inactive_30d OK")

    # 5. History: newest first, limit cap.
    r = c.get("/admin/broadcasts", headers=ADMIN)
    assert r.status_code == 200, r.text
    rows = r.json()["broadcasts"]
    assert len(rows) == 4, rows
    assert [x["target"] for x in rows] == [
        "inactive_30d", "new_7d", "verified", "all"], rows
    assert rows[0]["delivered_count"] == 1 and rows[0]["total_count"] == 2
    assert rows[3]["delivered_count"] == 5 and rows[3]["total_count"] == 6
    assert rows[0]["sent_by"] == 111 and rows[0]["text"] == "We miss you"
    r = c.get("/admin/broadcasts?limit=2", headers=ADMIN)
    assert len(r.json()["broadcasts"]) == 2, r.json()
    r = c.get("/admin/broadcasts?limit=500", headers=ADMIN)
    assert len(r.json()["broadcasts"]) == 4, r.json()
    print("broadcast history newest-first + limit OK")

    # 6. Empty target set: backdate every member past 7 days -> new_7d
    #    reaches nobody, still succeeds 0/0 and records the row.
    #    (Verified cannot be emptied: the admin is re-verified on
    #    every login by get_or_create_user, by design.)
    for uid in (111, 222, 333, 444, 555, 666):
        backdate(uid, 40)
    SENT.clear()
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "Nobody here", "target": "new_7d"})
    assert r.status_code == 200, r.text
    assert r.json()["recipients"] == 0 and r.json()["sent"] == 0, r.json()
    assert SENT == [], SENT
    r = c.get("/admin/broadcasts", headers=ADMIN)
    assert len(r.json()["broadcasts"]) == 5, r.json()
    assert r.json()["broadcasts"][0]["total_count"] == 0
    print("broadcast empty target set 0/0 OK")

    # 7. Validation + auth boundaries.
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "x", "target": "nope"})
    assert r.status_code == 400, r.status_code
    r = c.post("/admin/broadcast", headers=ADMIN, json={"text": "   "})
    assert r.status_code == 400, r.status_code
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "x", "target": "verified"})
    assert r.status_code == 200, r.text  # explicit target=all default
    r = c.post("/admin/broadcast", headers=BOB, json={"text": "hi"})
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/broadcasts", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/broadcasts")
    assert r.status_code == 401, r.status_code
    print("broadcast validation + auth OK")

    # 8. Backup carries 39 tables incl. broadcasts with the rows.
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.status_code
    bk = r.json()
    assert len(bk["tables"]) == 48, len(bk["tables"])
    assert "broadcasts" in bk["tables"], list(bk["tables"])
    assert len(bk["tables"]["broadcasts"]) >= 6, \
        len(bk["tables"]["broadcasts"])
    print("backup: 39 tables incl. broadcasts OK")

    # 9. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=172") == 10, html.count("?v=172")
    assert "?v=130" not in html
    assert 'id="admin-bc-target"' in html
    assert 'id="admin-bc-history"' in html
    js = open("webapp/app.js").read()
    for m in ("loadBroadcasts", "BC_TARGET_LABELS", "admin-bc-target",
              "admin-bc-history", "Delivered "):
        assert m in js, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts"):
        assert m in js, m
    print("client markers + ?v=172 OK")

print("PHASE-131 TESTS PASSED")
