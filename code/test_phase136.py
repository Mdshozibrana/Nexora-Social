"""Phase-136 tests: private account (follow requests).

Covers: /me/privacy toggle on/off (self only; unauthenticated
401; official account 400); follow public -> immediate follow;
follow private -> pending request ("requested", NO follow row),
duplicate request 400; /me/follow-requests lists it (with the
requester's name); accept -> follow row + requester notified;
accept again 404; accept another member's request 404; reject
-> no follow row, request marked rejected; cancelling a pending request (DELETE /users/{id}/follow-request)
removes it; private posts hidden from a non-follower in
Explore feed, Following feed, profile posts (locked) and
GET /posts/{id} (403), visible to a follower and to self; going
private keeps existing followers; trending excludes private
posts; hashtag search hides private posts but user search still
finds the account; public accounts unaffected; backup 39 tables
incl. follow_requests rows; ?v=209 x5, no ?v=135; private-account
client markers + Phase 123-135 markers intact.
"""
import hashlib, hmac, json, os, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase136.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

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


ALICE = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")
DAVE = H(444, "Dave")
EVE = H(555, "Eve")
OFF = H(1, "Nexora")


def follows(a, b):
    with SessionLocal() as db:
        return db.query(models.Follow).filter_by(
            follower_id=a, following_id=b).first() is not None


def pending_req(requester, target):
    with SessionLocal() as db:
        return db.query(models.FollowRequest).filter_by(
            requester_id=requester, target_id=target,
            status="pending").first()


def req_status(requester, target):
    with SessionLocal() as db:
        r = db.query(models.FollowRequest).filter_by(
            requester_id=requester, target_id=target).order_by(
            models.FollowRequest.id.desc()).first()
        return r.status if r else None


def notif_count(uid, ntype):
    with SessionLocal() as db:
        return db.query(models.Notification).filter_by(
            user_id=uid, type=ntype).count()


def feed_ids(c, headers, tab="explore"):
    r = c.get(f"/feed?tab={tab}", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE, EVE, OFF):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Privacy toggle: on/off, unauthenticated, official guard.
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"is_private": True}, r.json()
    r = c.get("/users/111", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["is_private"] is True, r.json()
    assert r.json()["has_pending_request"] is False, r.json()
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": False})
    assert r.json() == {"is_private": False}, r.json()
    r = c.post("/me/privacy", json={"is_private": True})
    assert r.status_code == 401, r.status_code
    r = c.post("/me/privacy", headers=OFF, json={"is_private": True})
    assert r.status_code == 400, r.text
    print("privacy toggle OK (on/off, 401, official 400)")

    # 2. Follow public -> immediate follow.
    r = c.post("/users/111/follow", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["following"] is True, r.json()
    assert r.json()["requested"] is False, r.json()
    assert follows(222, 111)
    print("follow public OK (immediate follow)")

    # 3. Going private keeps the existing follower.
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": True})
    assert r.json() == {"is_private": True}, r.json()
    assert follows(222, 111), "going private must not drop followers"
    print("going private keeps followers OK")

    # 4. Follow private -> pending request, no follow row.
    r = c.post("/users/111/follow", headers=CAROL)
    assert r.status_code == 200, r.text
    assert r.json()["following"] is False, r.json()
    assert r.json()["requested"] is True, r.json()
    assert not follows(333, 111), "a request must not create a follow"
    assert pending_req(333, 111) is not None
    r = c.post("/users/111/follow", headers=CAROL)
    assert r.status_code == 400, r.text
    r = c.get("/users/111", headers=CAROL)
    assert r.json()["has_pending_request"] is True, r.json()
    assert notif_count(111, "follow_request") >= 1, \
        "the target must get a follow-request notification"
    print("follow private -> request OK (no follow row, dup 400)")

    # 5. Accept: follow row appears, requester notified.
    r = c.get("/me/follow-requests", headers=ALICE)
    assert r.status_code == 200, r.text
    rows = r.json()["follow_requests"]
    assert len(rows) == 1, rows
    assert rows[0]["requester_id"] == 333, rows
    assert rows[0]["first_name"] == "Carol", rows
    req_id = rows[0]["id"]
    # Phase 183 (audit M19): acceptance notifies under
    # "follow_request", not "follow".
    n0 = notif_count(333, "follow_request")
    r = c.post(f"/follow-requests/{req_id}/accept", headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True, r.json()
    assert follows(333, 111), "accept must create the follow"
    assert req_status(333, 111) == "accepted"
    assert notif_count(333, "follow_request") > n0, \
        "the requester must be told the request was accepted"
    r = c.post(f"/follow-requests/{req_id}/accept", headers=ALICE)
    assert r.status_code == 404, r.text
    print("accept OK (follow row + notification, again 404)")

    # 6. Reject: no follow row, request marked rejected.
    r = c.post("/users/111/follow", headers=DAVE)
    assert r.json()["requested"] is True, r.json()
    r = c.get("/me/follow-requests", headers=ALICE)
    dave_req = [x for x in r.json()["follow_requests"]
                if x["requester_id"] == 444]
    assert len(dave_req) == 1, r.json()
    r = c.post(f"/follow-requests/{dave_req[0]['id']}/reject",
               headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["rejected"] is True, r.json()
    assert not follows(444, 111), "reject must not create a follow"
    assert req_status(444, 111) == "rejected"
    r = c.get("/me/follow-requests", headers=ALICE)
    assert r.json()["follow_requests"] == [], r.json()
    print("reject OK (no follow, marked rejected)")

    # 7. Accepting someone else's request -> 404.
    r = c.post("/users/111/follow", headers=EVE)
    assert r.json()["requested"] is True, r.json()
    r = c.get("/me/follow-requests", headers=ALICE)
    eve_req = [x for x in r.json()["follow_requests"]
               if x["requester_id"] == 555]
    assert len(eve_req) == 1, r.json()
    r = c.post(f"/follow-requests/{eve_req[0]['id']}/accept",
               headers=DAVE)
    assert r.status_code == 404, r.text
    r = c.post(f"/follow-requests/{eve_req[0]['id']}/reject",
               headers=BOB)
    assert r.status_code == 404, r.text
    print("accept/reject someone else's request -> 404 OK")

    # 8. Cancelling a pending request removes it (and a second
    # POST /follow while one is pending is a 400, not a cancel).
    r = c.post("/users/111/follow", headers=EVE)
    assert r.status_code == 400, r.text
    r = c.delete("/users/111/follow-request", headers=EVE)
    assert r.status_code == 200, r.text
    assert r.json()["cancelled"] is True, r.json()
    assert pending_req(555, 111) is None, "pending request must be gone"
    assert not follows(555, 111)
    r = c.delete("/users/111/follow-request", headers=EVE)
    assert r.status_code == 404, r.text
    print("cancel pending request OK")

    # 9. Privacy enforcement: Alice posts while private.
    r = c.post("/posts", headers=ALICE,
               json={"caption": "alice secret post #secret"})
    assert r.status_code == 200, r.text
    alice_post = r.json()["id"]
    r = c.post("/posts", headers=BOB,
               json={"caption": "bob public post"})
    assert r.status_code == 200, r.text
    bob_post = r.json()["id"]
    # Non-follower Dave: hidden everywhere.
    assert alice_post not in feed_ids(c, DAVE, "explore")
    assert alice_post not in feed_ids(c, DAVE, "following")
    r = c.get("/users/111/posts", headers=DAVE)
    assert r.status_code == 200, r.text
    assert r.json()["posts"] == [], r.json()
    assert r.json()["locked"] is True, r.json()
    r = c.get(f"/posts/{alice_post}", headers=DAVE)
    assert r.status_code == 403, r.status_code
    # Followers Bob + Carol: visible everywhere.
    assert alice_post in feed_ids(c, BOB, "explore")
    assert alice_post in feed_ids(c, BOB, "following")
    assert alice_post in feed_ids(c, CAROL, "explore")
    r = c.get("/users/111/posts", headers=BOB)
    assert alice_post in [p["id"] for p in r.json()["posts"]], r.json()
    assert r.json().get("locked") is not True
    r = c.get(f"/posts/{alice_post}", headers=CAROL)
    assert r.status_code == 200, r.text
    # Alice herself: visible.
    assert alice_post in feed_ids(c, ALICE, "explore")
    r = c.get(f"/posts/{alice_post}", headers=ALICE)
    assert r.status_code == 200, r.text
    # Bob's public post is visible to everyone.
    assert bob_post in feed_ids(c, DAVE, "explore")
    print("privacy enforcement OK (hidden for non-followers, visible for followers/self)")

    # 10. Trending excludes private posts.
    r = c.post(f"/posts/{alice_post}/like", headers=CAROL)
    assert r.status_code == 200, r.text
    r = c.post(f"/posts/{bob_post}/like", headers=CAROL)
    assert r.status_code == 200, r.text
    r = c.get("/trending/posts", headers=DAVE)
    assert r.status_code == 200, r.text
    trend_ids = [p["id"] for p in r.json()["posts"]]
    assert alice_post not in trend_ids, trend_ids
    assert bob_post in trend_ids, trend_ids
    print("trending excludes private posts OK")

    # 11. Search: hashtag hides private posts, user search finds her.
    r = c.get("/search?q=%23secret", headers=DAVE)
    assert r.status_code == 200, r.text
    assert r.json()["posts"] == [], r.json()
    r = c.get("/search?q=%23secret", headers=CAROL)
    assert alice_post in [p["id"] for p in r.json()["posts"]], r.json()
    r = c.get("/search?q=Alice", headers=DAVE)
    assert 111 in [u["telegram_id"] for u in r.json()["users"]], r.json()
    print("search OK (hashtag hidden, user found)")

    # 12. Backup carries 39 tables incl. follow_requests rows.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.status_code
    bk = r.json()
    assert len(bk["tables"]) == 55, len(bk["tables"])
    assert "follow_requests" in bk["tables"], list(bk["tables"])
    assert len(bk["tables"]["follow_requests"]) >= 2, \
        len(bk["tables"]["follow_requests"])
    print("backup: 39 tables incl. follow_requests OK")

    # 13. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=209") == 10, html.count("?v=209")
    assert "?v=135" not in html
    js = open("webapp/app.js").read()
    for m in ("loadFollowRequests", "Follow requests", "Private account",
              "private-lock", "privacy-row", "/me/privacy",
              "/me/follow-requests", "Requested ✓", "follow_request",
              "has_pending_request", "This account is private",
              "/follow-request"):
        assert m in js, m
    main_src = open("app/main.py").read()
    for m in ("Follow request already pending", "cancel_follow_request",
              "def _can_see_posts"):
        assert m in main_src, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus", "openTipSheet", "openInsights",
              "ins-chart", "ins-table", "schedLocalInput", "loadScheduled",
              "composer-schedule"):
        assert m in js, m
    css = open("webapp/style.css").read()
    assert ".private-lock" in css and ".privacy-row" in css
    print("client markers + ?v=209 OK")

print("PHASE-136 TESTS PASSED")
