"""Phase-127 tests: crypto payout queue (Monetization payout).

Design (owner, Nov 14): payouts in crypto (TON / Gram / USDT); NO
hardcoded points->money rate — the admin sets the crypto amount at
approval from real income. A member saves a wallet, requests a
payout in points (gate unlocked, one pending at a time); the admin
approves (amount + currency, points leave the balance then) or
rejects, then marks paid with the tx reference once the crypto is
sent manually. No minimum payout enforced.

Tests: wallet save/validation; request validation (no wallet, bad
points, over balance, gate locked, second pending); admin list +
decide (approve needs amount + currency, deducts points, notifies,
audits; reject costs nothing; non-admin 403; paid only from
approved); backup carries 35 tables incl. payout_requests with a
restore round-trip; ?v=208 (x5), ?v=208 gone; client markers; the
monetization endpoint still works after the gate-helper refactor.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase127.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402
from app import services  # noqa: E402

def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)





def H(uid, name, auth_date=None):
    return {"X-Init-Data": make_init_data(
        {"id": uid, "first_name": name}, auth_date)}


UID = {"A": 881, "B": 882, "C": 883, "ADMIN": 999}
HA = H(UID["ADMIN"], "Admin")


def unlock_member(db, uid):
    """Build a member who meets all six monetization gate targets,
    via direct rows (the same counts /me/monetization computes)."""
    u = db.get(models.User, uid)
    if u is None:
        u = models.User(telegram_id=uid, first_name="C")
        db.add(u)
        db.flush()
    for i in range(500):
        fid = 10000 + i
        db.add(models.User(telegram_id=fid, first_name=f"F{i}"))
        db.add(models.Follow(follower_id=fid, following_id=uid))
    for i in range(12):
        nid = 20000 + i
        db.add(models.User(telegram_id=nid, first_name=f"R{i}"))
        db.add(models.Referral(referrer_id=uid, new_user_id=nid,
                               qualified=True))
    for i in range(25):
        db.add(models.Post(user_id=uid, type="text", caption=f"p{i}"))
    today = datetime.utcnow().date()
    for d in range(30):
        day = (today - timedelta(days=d)).isoformat()
        db.add(models.DailyClaim(user_id=uid, task_key="checkin",
                                 day=day))
    services.award_points(db, uid, 5000, "post")
    u = db.get(models.User, uid)
    u.created_at = datetime.utcnow() - timedelta(days=15)
    db.commit()


def balance(db, uid):
    return db.get(models.User, uid).points_balance


BASE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(BASE, "webapp", "index.html")).read()
JS = open(os.path.join(BASE, "webapp", "app.js")).read()
SRC = open(os.path.join(BASE, "app", "main.py")).read()
MODELS_SRC = open(os.path.join(BASE, "app", "models.py")).read()
CONFIG_SRC = open(os.path.join(BASE, "app", "config.py")).read()

with TestClient(app) as c:
    r = c.get("/health")
    assert r.status_code == 200, r.text

    # ------------------------------------------------------ source guards --
    # Phase 126 lesson: no integer default on a boolean column in
    # raw migration SQL (Postgres rejects it, SQLite accepts it).
    assert "BOOLEAN DEFAULT 0" not in SRC, "boolean DEFAULT 0 present"
    assert "wallet_address VARCHAR(256)" in SRC
    assert "wallet_network VARCHAR(16)" in SRC
    assert "class PayoutRequest" in MODELS_SRC
    assert 'PAYOUT_NETWORKS = ("TON", "Gram", "USDT")' in CONFIG_SRC
    assert '"payout": (10, 3600)' in CONFIG_SRC
    assert '"payout_admin": (120, 3600)' in CONFIG_SRC
    assert "PAYOUT:" in SRC, "Nexa manual has no PAYOUT line"
    print("source guards: no BOOLEAN DEFAULT 0, wallet + networks OK")

    # ------------------------------------------------------------ wallet --
    # Fresh member: no wallet yet.
    r = c.get("/me/wallet", headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    assert r.json() == {"wallet_network": None,
                        "wallet_address": None}, r.json()
    # Bad network / empty address rejected.
    r = c.post("/me/wallet", json={"network": "BTC", "address": "x"},
               headers=H(UID["A"], "A"))
    assert r.status_code == 400, r.status_code
    r = c.post("/me/wallet", json={"network": "TON", "address": "  "},
               headers=H(UID["A"], "A"))
    assert r.status_code == 400, r.status_code
    r = c.post("/me/wallet", json={"network": "TON", "address": "x" * 257},
               headers=H(UID["A"], "A"))
    assert r.status_code == 400, r.status_code
    # Save + overwrite.
    r = c.post("/me/wallet",
               json={"network": "USDT", "address": "TQaaa111"},
               headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    assert r.json()["wallet_network"] == "USDT"
    r = c.post("/me/wallet",
               json={"network": "TON", "address": "EQbbb222"},
               headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    r = c.get("/me/wallet", headers=H(UID["A"], "A"))
    assert r.json() == {"wallet_network": "TON",
                        "wallet_address": "EQbbb222"}, r.json()
    print("wallet: validation + save + overwrite OK")

    # ----------------------------------------------------- request guards --
    # B: no wallet yet -> 400.
    r = c.post("/me/payout/request", json={"points": 100},
               headers=H(UID["B"], "B"))
    assert r.status_code == 400, r.status_code
    c.post("/me/wallet", json={"network": "Gram", "address": "UQccc333"},
           headers=H(UID["B"], "B"))
    # Bad points -> 400.
    for bad in (0, -5):
        r = c.post("/me/payout/request", json={"points": bad},
                   headers=H(UID["B"], "B"))
        assert r.status_code == 400, (bad, r.status_code)
    # Gate locked (fresh member, wallet saved) -> 403, not 400.
    r = c.post("/me/payout/request", json={"points": 10},
               headers=H(UID["B"], "B"))
    assert r.status_code == 403, r.status_code
    print("request guards: no-wallet 400, bad points 400, locked 403 OK")

    # -------------------------------------------------- unlocked member C --
    db = SessionLocal()
    unlock_member(db, UID["C"])
    db.close()
    r = c.get("/me/monetization", headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    assert r.json()["unlocked"] is True, r.json()
    r = c.get("/me/monetization", headers=H(UID["A"], "A"))
    assert r.json()["unlocked"] is False
    print("monetization gate: unlocked member True, fresh member False OK")
    c.post("/me/wallet", json={"network": "TON", "address": "EQccc444"},
           headers=H(UID["C"], "C"))
    # Over the 5000-point balance -> 400.
    r = c.post("/me/payout/request", json={"points": 5001},
               headers=H(UID["C"], "C"))
    assert r.status_code == 400, r.status_code
    # Success: pending request, listed under /me/payouts.
    r = c.post("/me/payout/request", json={"points": 100},
               headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    req1 = r.json()
    assert req1["status"] == "pending" and req1["points"] == 100
    assert req1["wallet_address"] == "EQccc444"
    assert req1["wallet_network"] == "TON"
    r = c.get("/me/payouts", headers=H(UID["C"], "C"))
    assert [q["id"] for q in r.json()["requests"]] == [req1["id"]]
    # A second pending request -> 400.
    r = c.post("/me/payout/request", json={"points": 50},
               headers=H(UID["C"], "C"))
    assert r.status_code == 400, r.status_code
    print("request: over-balance 400, success pending, second 400 OK")

    # ------------------------------------------------------------- admin --
    r = c.get("/admin/payouts", headers=H(UID["A"], "A"))
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/payouts", headers=HA)
    assert r.status_code == 200, r.text
    assert r.json()["pending_count"] == 1
    got = r.json()["requests"][0]
    assert got["id"] == req1["id"] and got["first_name"] == "C"
    assert got["wallet_address"] == "EQccc444"
    r = c.get("/admin/payouts?status=pending", headers=HA)
    assert len(r.json()["requests"]) == 1
    r = c.get("/admin/payouts?status=bogus", headers=HA)
    assert r.status_code == 400, r.status_code
    r = c.get("/admin/payouts?status=paid", headers=HA)
    assert r.json()["requests"] == []
    print("admin list: 403 for members, member info + filter OK")

    # Decide: unknown 404; approve without amount 400; bad currency
    # 400; non-number / zero amount 400.
    r = c.post("/admin/payouts/99999/decide",
               json={"action": "approve", "amount": "1", "currency": "TON"},
               headers=HA)
    assert r.status_code == 404, r.status_code
    r = c.post(f"/admin/payouts/{req1['id']}/decide",
               json={"action": "approve"}, headers=HA)
    assert r.status_code == 400, r.status_code
    r = c.post(f"/admin/payouts/{req1['id']}/decide",
               json={"action": "approve", "amount": "10",
                     "currency": "BTC"}, headers=HA)
    assert r.status_code == 400, r.status_code
    r = c.post(f"/admin/payouts/{req1['id']}/decide",
               json={"action": "approve", "amount": "abc",
                     "currency": "TON"}, headers=HA)
    assert r.status_code == 400, r.status_code
    r = c.post(f"/admin/payouts/{req1['id']}/decide",
               json={"action": "approve", "amount": "0",
                     "currency": "TON"}, headers=HA)
    assert r.status_code == 400, r.status_code
    # Approve: amount + currency stored, points deducted (5000->4900),
    # ledger row, notification + audit.
    db = SessionLocal()
    before = balance(db, UID["C"])
    db.close()
    assert before == 5000, before
    r = c.post(f"/admin/payouts/{req1['id']}/decide",
               json={"action": "approve", "amount": "12.5",
                     "currency": "TON"}, headers=HA)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "approved" and d["amount"] == "12.5"
    assert d["currency"] == "TON" and d["decided_by"] == 999
    db = SessionLocal()
    assert balance(db, UID["C"]) == 4900, balance(db, UID["C"])
    led = db.query(models.PointsLedger).filter_by(
        user_id=UID["C"], reason="payout").all()
    assert len(led) == 1 and led[0].amount == -100, led
    assert db.query(models.Notification).filter_by(
        user_id=UID["C"], type="payout").count() >= 1
    assert db.query(models.AdminAuditLog).filter_by(
        action="payout_approve").count() == 1
    db.close()
    # Already decided -> 400.
    r = c.post(f"/admin/payouts/{req1['id']}/decide",
               json={"action": "reject"}, headers=HA)
    assert r.status_code == 400, r.status_code
    print("decide approve: validation + deduction + notify + audit OK")

    # Paid: only from approved. New pending request first.
    r = c.post("/me/payout/request", json={"points": 50},
               headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    req2 = r.json()
    r = c.post(f"/admin/payouts/{req2['id']}/paid",
               json={"tx_ref": "tx1"}, headers=HA)
    assert r.status_code == 400, r.status_code
    r = c.post(f"/admin/payouts/{req2['id']}/decide",
               json={"action": "approve", "amount": "5",
                     "currency": "USDT"}, headers=HA)
    assert r.status_code == 200, r.text
    r = c.post(f"/admin/payouts/{req2['id']}/paid",
               json={"tx_ref": "  "}, headers=HA)
    assert r.status_code == 400, r.status_code
    r = c.post(f"/admin/payouts/{req2['id']}/paid",
               json={"tx_ref": "tx-hash-abc123"}, headers=HA)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "paid" and d["tx_ref"] == "tx-hash-abc123"
    assert d["paid_at"] is not None
    db = SessionLocal()
    assert balance(db, UID["C"]) == 4850, balance(db, UID["C"])
    assert db.query(models.AdminAuditLog).filter_by(
        action="payout_paid").count() == 1
    assert db.query(models.Notification).filter_by(
        user_id=UID["C"], type="payout").count() >= 2
    db.close()
    print("paid: pending 400, empty tx 400, paid + tx_ref + audit OK")

    # Reject: costs nothing, and the member may request again.
    r = c.post("/me/payout/request", json={"points": 200},
               headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    req3 = r.json()
    r = c.post(f"/admin/payouts/{req3['id']}/decide",
               json={"action": "reject"}, headers=HA)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    db = SessionLocal()
    assert balance(db, UID["C"]) == 4850, balance(db, UID["C"])
    assert db.query(models.AdminAuditLog).filter_by(
        action="payout_reject").count() == 1
    db.close()
    r = c.post("/me/payout/request", json={"points": 10},
               headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    req4 = r.json()
    assert req4["status"] == "pending"
    print("reject: no deduction, re-request allowed OK")

    # ------------------------------------------------------------ backup --
    r = c.get("/admin/backup", headers=HA)
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers.get("content-disposition", "")
    b = r.json()
    assert b["format"] == "nexora-backup" and b["version"] == 1
    from app.main import _BACKUP_TABLES  # noqa: E402
    assert set(b["tables"]) == {n for n, _ in _BACKUP_TABLES}
    assert len(b["tables"]) == 55, len(b["tables"])
    assert "payout_requests" in b["tables"]
    assert len(b["tables"]["payout_requests"]) == 4, \
        len(b["tables"]["payout_requests"])
    assert any(q["tx_ref"] == "tx-hash-abc123"
               for q in b["tables"]["payout_requests"])
    r = c.get("/admin/backup", headers=H(UID["A"], "A"))
    assert r.status_code == 403, r.status_code
    print("backup: 39 tables incl. payout_requests, rows present OK")
    # Round-trip: wipe payout_requests, restore, they come back.
    db = SessionLocal()
    db.query(models.PayoutRequest).delete()
    db.commit()
    assert db.query(models.PayoutRequest).count() == 0
    db.close()
    r = c.post("/admin/restore", headers=HA,
               json={"confirm": "RESTORE", "backup": b})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    assert db.query(models.PayoutRequest).count() == 4
    paid = db.query(models.PayoutRequest).filter_by(status="paid").one()
    assert paid.tx_ref == "tx-hash-abc123"
    assert paid.amount == "5" and paid.currency == "USDT"
    db.close()
    print("backup restore round-trip: payout rows back identical OK")

    # ------------------------------------------------------------- client --
    assert HTML.count("?v=208") == 10, HTML.count("?v=208")
    assert "?v=126" not in HTML
    assert "app.js?v=208" in HTML and "style.css?v=208" in HTML
    for marker in ("loadPayoutBox", "loadPayoutList", "loadPayouts",
                   "decidePayout", "markPayoutPaid", "payout-network",
                   "payout-address", "payout-points", "payout-request",
                   "payout-my-list", "payout-box", "/me/wallet",
                   "/me/payout/request", "/admin/payouts", "cp-count-payouts"):
        assert marker in JS, marker
    for marker in ("cp-sec-payouts", "admin-payouts",
                   "cp-count-payouts", "Payout requests"):
        assert marker in HTML, marker
    for marker in ("topScroller", "pollBlock", "loadDrafts",
                   "renderPh", "goFeedTo", "loadTrending"):
        assert marker in JS, marker
    print("client: ?v=208 + payout markers + 123-126 markers OK")

print("phase127: wallet + request + admin + backup + client OK")
