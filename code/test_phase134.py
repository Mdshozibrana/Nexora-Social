"""Phase-134 tests: post insights (creator analytics).

Covers: per-post totals (views/likes/comments/reposts/tips)
+ 14-day daily series (UTC dates, newest last, zeros on empty
days, 15-day-old activity outside the window); best_day is the
highest-view day; author 200 / other member 403 / unknown 404 /
unauthenticated 401; /me/insights totals + top-5 ordering;
GET /posts/{id} single-post fetch; backup still 39 tables;
?v=164 x5, no ?v=133; insights client markers + Phase 123-133
markers intact.
"""
import hashlib, hmac, json, os, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase134.db"

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


def H(uid, name, auth_date=None):
    return {"X-Init-Data": make_init_data(
        {"id": uid, "first_name": name}, auth_date)}

ALICE = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")
DAVE = H(444, "Dave")
EVE = H(555, "Eve")
FRANK = H(666, "Frank")
GRACE = H(777, "Grace")


def ago(days):
    return datetime.utcnow() - timedelta(days=days)


def seed_activity(post_id):
    """Views/likes/comments/tips spread over several days.
    15-day-old rows must fall OUTSIDE the 14-day window."""
    with SessionLocal() as db:
        # Views: today 2 (Carol, Dave), 3d ago 1 (Eve),
        # 13d ago 1 (Frank), 15d ago 1 (Grace) -> total 5.
        for uid, days in ((333, 0), (444, 0), (555, 3),
                          (666, 13), (777, 15)):
            db.add(models.PostView(post_id=post_id, user_id=uid,
                                   created_at=ago(days)))
        # Likes: today 1 (Carol), 3d ago 2 (Dave, Eve),
        # 13d ago 1 (Frank), 15d ago 1 (Grace) -> total 5.
        for uid, days in ((333, 0), (444, 3), (555, 3),
                          (666, 13), (777, 15)):
            db.add(models.Like(post_id=post_id, user_id=uid,
                               created_at=ago(days)))
        # Comments: today 2 (Carol, Dave), 3d ago 1 (Eve),
        # 15d ago 1 (Grace) -> total 4.
        for uid, days in ((333, 0), (444, 0), (555, 3), (777, 15)):
            db.add(models.Comment(post_id=post_id, user_id=uid,
                                  text="nice", created_at=ago(days)))
        # Tips on the post: 50 + 100 stars -> 150 stars, count 2.
        db.add(models.Tip(from_user_id=333, to_user_id=111,
                          post_id=post_id, amount_stars=50,
                          telegram_payment_charge_id="t134a",
                          created_at=ago(1)))
        db.add(models.Tip(from_user_id=444, to_user_id=111,
                          post_id=post_id, amount_stars=100,
                          telegram_payment_charge_id="t134b",
                          created_at=ago(0)))
        db.commit()


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE, EVE, FRANK, GRACE):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    r = c.post("/posts", headers=ALICE,
               json={"type": "text", "caption": "hello world analytics"})
    assert r.status_code == 200, r.text
    post1 = r.json()["id"]
    r = c.post("/posts", headers=ALICE,
               json={"type": "text", "caption": "second post"})
    assert r.status_code == 200, r.text
    post2 = r.json()["id"]
    seed_activity(post1)
    # Post 2 gets a single view today (top-5 ordering check).
    with SessionLocal() as db:
        db.add(models.PostView(post_id=post2, user_id=333,
                               created_at=ago(0)))
        db.commit()
    # Bob reposts Alice's post -> repost_count 1.
    r = c.post(f"/posts/{post1}/repost", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["repost_count"] == 1, r.json()

    # 1. Per-post insights: totals + 14-day series + best day.
    r = c.get(f"/posts/{post1}/insights", headers=ALICE)
    assert r.status_code == 200, r.text
    ins = r.json()
    assert ins["post_id"] == post1, ins
    assert ins["totals"] == {"views": 5, "likes": 5, "comments": 4,
                             "reposts": 1, "tips_stars": 150,
                             "tips_count": 2}, ins["totals"]
    today = datetime.utcnow().date()
    assert len(ins["daily"]) == 14, len(ins["daily"])
    assert ins["daily"][0]["date"] == (today - timedelta(days=13)).isoformat()
    assert ins["daily"][-1]["date"] == today.isoformat()
    by_date = {d["date"]: d for d in ins["daily"]}
    assert by_date[today.isoformat()] == {
        "date": today.isoformat(), "views": 2, "likes": 1,
        "comments": 2}, by_date[today.isoformat()]
    d3 = (today - timedelta(days=3)).isoformat()
    assert by_date[d3] == {"date": d3, "views": 1, "likes": 2,
                           "comments": 1}, by_date[d3]
    d13 = (today - timedelta(days=13)).isoformat()
    assert by_date[d13] == {"date": d13, "views": 1, "likes": 1,
                            "comments": 0}, by_date[d13]
    # 15-day-old activity is outside the window: window sums
    # are 4 views / 4 likes / 3 comments, not the all-time 5/5/4.
    assert sum(d["views"] for d in ins["daily"]) == 4
    assert sum(d["likes"] for d in ins["daily"]) == 4
    assert sum(d["comments"] for d in ins["daily"]) == 3
    for d in ins["daily"]:
        if d["date"] not in (today.isoformat(), d3, d13):
            assert d == {"date": d["date"], "views": 0, "likes": 0,
                         "comments": 0}, d
    assert ins["best_day"] == {"date": today.isoformat(),
                               "views": 2}, ins["best_day"]
    print("post insights totals + daily series + best_day OK")

    # 2. Insights on the repost id resolves to the original.
    with SessionLocal() as db:
        repost_row = db.query(models.Post).filter_by(
            user_id=222, repost_of_id=post1,
            is_deleted=False).one()
    r = c.get(f"/posts/{repost_row.id}/insights", headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["post_id"] == post1, r.json()
    print("insights via repost id resolves to original OK")

    # 3. Auth boundaries: other member 403, unknown 404, no auth 401.
    r = c.get(f"/posts/{post1}/insights", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get("/posts/999999/insights", headers=ALICE)
    assert r.status_code == 404, r.status_code
    r = c.get(f"/posts/{post1}/insights")
    assert r.status_code == 401, r.status_code
    print("insights auth boundaries OK")

    # 4. /me/insights: totals + top-5 ordering (post1 first).
    r = c.get("/me/insights", headers=ALICE)
    assert r.status_code == 200, r.text
    mine = r.json()
    assert mine["totals"] == {"views": 6, "likes": 5, "comments": 4,
                              "posts": 2, "tips_stars": 150}, mine["totals"]
    assert len(mine["top_posts"]) == 2, mine["top_posts"]
    assert mine["top_posts"][0]["id"] == post1
    assert mine["top_posts"][0]["views"] == 5
    assert mine["top_posts"][0]["caption_excerpt"] == \
        "hello world analytics"
    assert mine["top_posts"][1]["id"] == post2
    assert mine["top_posts"][1]["views"] == 1
    r = c.get("/me/insights")
    assert r.status_code == 401, r.status_code
    print("/me/insights totals + top-5 OK")

    # 5. Single-post fetch (top-posts tap target).
    r = c.get(f"/posts/{post1}", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == post1
    assert r.json()["caption"] == "hello world analytics"
    r = c.get("/posts/999999", headers=BOB)
    assert r.status_code == 404, r.status_code
    print("GET /posts/{id} OK")

    # 6. Backup still 39 tables (no new table this phase).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.status_code
    assert len(r.json()["tables"]) == 44, len(r.json()["tables"])
    print("backup: 39 tables OK")

    # 7. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=164") == 10, html.count("?v=164")
    assert "?v=133" not in html
    js = open("webapp/app.js").read()
    for m in ("openInsights", "openTopPost", "My insights",
              "ins-chart", "ins-table", "ins-totals",
              "/posts/\" + postId + \"/insights", "/me/insights",
              "/posts/\" + postId"):
        assert m in js, m
    css = open("webapp/style.css").read()
    for m in (".ins-chart", ".ins-bar", ".ins-table", ".ins-totals"):
        assert m in css, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus", "openTipSheet", "My tips",
              "loadMyQr"):
        assert m in js, m
    print("client markers + ?v=164 OK")

print("PHASE-134 TESTS PASSED")
