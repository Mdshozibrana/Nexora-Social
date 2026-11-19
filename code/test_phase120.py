"""Phase-120 tests: Verify by Username section in the Admin Control Panel.

The admin types a @username, sees the member's card (photo, name,
followers, posts, tick status) and grants or removes the blue tick
on the spot. Lookup is exact and case-insensitive, @ optional.
A grant/revoke that changes nothing is a harmless no-op (no audit
row, no notification). The official account can never change
through here. A real change audits + notifies the member, like the
verification-approval grant does. The old member toggle
(POST /admin/users/{id}/verify) now runs through the same shared
core helper — this suite proves it still works.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase120.db"

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
    secret = hmac.new(b"WebAppData",
                      os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


ADMIN = 999
HA = H(ADMIN, "Admin")
HB = H(882, "Bob")

ALICE = 881
BOB = 882
OFFICIAL = 1


def seed():
    db = SessionLocal()
    db.add(models.User(telegram_id=OFFICIAL, first_name="Nexora Social",
                       username="nexora", is_verified=True))
    db.add(models.User(telegram_id=ALICE, first_name="Alice",
                       username="alice_w"))
    db.add(models.User(telegram_id=BOB, first_name="Bob",
                       username="Bob_TheBuilder", is_verified=True))
    db.commit()
    db.close()


def audit_count(action, target):
    db = SessionLocal()
    n = db.query(models.AdminAuditLog).filter_by(
        action=action, target_id=target).count()
    db.close()
    return n


def notif_count(uid):
    db = SessionLocal()
    n = db.query(models.Notification).filter_by(
        user_id=uid, type="verification").count()
    db.close()
    return n


def is_verified(uid):
    db = SessionLocal()
    u = db.get(models.User, uid)
    v = bool(u.is_verified)
    db.close()
    return v


def test_client_markers():
    html = open("webapp/index.html").read()
    assert html.count("?v=150") == 9, html.count("?v=150")
    assert "?v=119" not in html
    for marker in ("cp-sec-verify", "vbu-q", "vbu-go", "vbu-result",
                   "vbu-status", "Verify by Username"):
        assert marker in html, marker
    js = open("webapp/app.js").read()
    for marker in ("wireVbu", "searchVbu", "applyVbu",
                   "verify-by-username", "by-username",
                   "Give blue tick", "Remove blue tick"):
        assert marker in js, marker
    # Phase 119 markers intact — Control Panel untouched otherwise.
    for marker in ("cp-nav", "maint-toggle", "audit-refresh",
                   "loadSiteControls", "loadAuditLog", "loadAdminDesigns"):
        assert marker in js or marker in html, marker
    # Phase 118 markers intact — repost + comment replies untouched.
    assert "repost-banner" in js and "Replying to" in js
    css = open("webapp/style.css").read()
    assert "comment-replies" in css or "comment-reply-btn" in css
    print("client markers OK (?v=150, verify-by-username section)")


def test_lookup_by_username():
    c = TestClient(app)
    r = c.get("/admin/users/by-username/alice_w", headers=HB)
    assert r.status_code == 403, r.status_code
    u = c.get("/admin/users/by-username/alice_w", headers=HA).json()
    assert u["telegram_id"] == ALICE and u["username"] == "alice_w", u
    assert u["first_name"] == "Alice" and u["is_verified"] is False, u
    assert u["followers"] == 0 and u["posts"] == 0, u
    # @ prefix and case do not matter.
    assert c.get("/admin/users/by-username/@alice_w",
                 headers=HA).json()["telegram_id"] == ALICE
    assert c.get("/admin/users/by-username/ALICE_W",
                 headers=HA).json()["telegram_id"] == ALICE
    assert c.get("/admin/users/by-username/Bob_TheBuilder",
                 headers=HA).json()["is_verified"] is True
    assert c.get("/admin/users/by-username/bob_thebuilder",
                 headers=HA).json()["telegram_id"] == BOB
    assert c.get("/admin/users/by-username/nobody_here",
                 headers=HA).status_code == 404
    off = c.get("/admin/users/by-username/nexora", headers=HA).json()
    assert off["telegram_id"] == OFFICIAL and off["is_verified"] is True
    print("lookup by username OK (exact / @ / case / 404 / 403)")


def test_grant_revoke_flow():
    c = TestClient(app)
    assert audit_count("verify_grant", ALICE) == 0
    r = c.post("/admin/verify-by-username", headers=HA,
               json={"username": "alice_w", "action": "grant"})
    assert r.status_code == 200, r.text
    assert r.json() == {"telegram_id": ALICE, "username": "alice_w",
                        "first_name": "Alice", "is_verified": True,
                        "changed": True}, r.json()
    assert is_verified(ALICE) is True
    assert audit_count("verify_grant", ALICE) == 1
    assert notif_count(ALICE) == 1
    # Grant again: harmless no-op — no extra audit, no extra notice.
    r = c.post("/admin/verify-by-username", headers=HA,
               json={"username": "@Alice_W", "action": "grant"})
    assert r.json()["changed"] is False
    assert r.json()["is_verified"] is True
    assert audit_count("verify_grant", ALICE) == 1
    assert notif_count(ALICE) == 1
    # Revoke, then revoke again.
    r = c.post("/admin/verify-by-username", headers=HA,
               json={"username": "alice_w", "action": "revoke"})
    assert r.json()["changed"] is True
    assert r.json()["is_verified"] is False
    assert is_verified(ALICE) is False
    assert audit_count("verify_revoke", ALICE) == 1
    assert notif_count(ALICE) == 2
    r = c.post("/admin/verify-by-username", headers=HA,
               json={"username": "alice_w", "action": "revoke"})
    assert r.json()["changed"] is False
    assert audit_count("verify_revoke", ALICE) == 1
    assert notif_count(ALICE) == 2
    print("grant / revoke / no-op OK")


def test_guards():
    c = TestClient(app)
    # Official account can never change through here.
    r = c.post("/admin/verify-by-username", headers=HA,
               json={"username": "nexora", "action": "revoke"})
    assert r.status_code == 400, r.status_code
    assert is_verified(OFFICIAL) is True
    # Unknown user, bad action, empty username, non-admin.
    assert c.post("/admin/verify-by-username", headers=HA,
                  json={"username": "ghost", "action": "grant"}
                  ).status_code == 404
    assert c.post("/admin/verify-by-username", headers=HA,
                  json={"username": "alice_w", "action": "tick"}
                  ).status_code == 400
    assert c.post("/admin/verify-by-username", headers=HA,
                  json={"username": "  @  ", "action": "grant"}
                  ).status_code == 400
    assert c.post("/admin/verify-by-username", headers=HB,
                  json={"username": "alice_w", "action": "grant"}
                  ).status_code == 403
    print("guards OK (official 400 / unknown 404 / bad action 400 / "
          "empty 400 / non-admin 403)")


def test_member_toggle_still_works():
    c = TestClient(app)
    # Bob starts verified (seeded); the old member toggle must still
    # flip him through the shared core helper.
    assert is_verified(BOB) is True
    r = c.post(f"/admin/users/{BOB}/verify", headers=HA,
               json={"verified": False})
    assert r.status_code == 200 and r.json()["is_verified"] is False
    assert is_verified(BOB) is False
    assert audit_count("verify_revoke", BOB) == 1
    r = c.post(f"/admin/users/{BOB}/verify", headers=HA,
               json={"verified": True})
    assert r.json()["is_verified"] is True
    print("member toggle still works through the shared core OK")


if __name__ == "__main__":
    seed()
    test_client_markers()
    test_lookup_by_username()
    test_grant_revoke_flow()
    test_guards()
    test_member_toggle_still_works()
    print("test_phase120: ALL OK")
