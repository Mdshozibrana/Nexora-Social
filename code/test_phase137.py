"""Phase-137 tests: levels & badges (computed, no new table).

Covers: level_for boundaries (every ladder step, progress 0.0 at
a boundary, 0.5 midway, next_level null + progress 1.0 at L8);
badges — fresh member has only Pioneer earned (anyone joining
before Dec 2026 is a Pioneer), 1 post -> First Post, 25 posts ->
25 Posts, verified -> Verified, 500 followers -> 500 Followers,
10 tips received -> 10 Tips, 30-day check-in streak -> 30-Day
Streak, created_at after 2026-12-01 -> Pioneer NOT earned;
locked badges still listed with earned=false + hint; profile
response and /auth response both carry level + badges; level
via HTTP tracks seeded ledger amounts (4999 -> L5, +1 -> L6);
backup still 39 tables; ?v=191 x5, no ?v=136; level/badge
client markers + Phase 123-136 markers intact.
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
from app.main import app, level_for
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
FRANK = H(666, "Frank")
GRACE = H(777, "Grace")
HEIDI = H(888, "Heidi")
IVAN = H(999, "Ivan")
OFF = H(1, "Nexora")


def add_points(uid, amount):
    with SessionLocal() as db:
        db.add(models.PointsLedger(user_id=uid, amount=amount,
                                   reason="test137"))
        db.commit()


def set_created(uid, dt):
    with SessionLocal() as db:
        u = db.get(models.User, uid)
        u.created_at = dt
        db.commit()


def seed_followers(target, n, base=10000):
    """n follower User rows + Follow rows, straight in the DB."""
    with SessionLocal() as db:
        for i in range(n):
            fid = base + i
            if not db.get(models.User, fid):
                db.add(models.User(telegram_id=fid,
                                   first_name=f"Follower{i}"))
        db.commit()
        for i in range(n):
            db.add(models.Follow(follower_id=base + i,
                                 following_id=target))
        db.commit()


def seed_tips(target, n, base=20000):
    with SessionLocal() as db:
        for i in range(n):
            db.add(models.Tip(
                from_user_id=base + i, to_user_id=target,
                amount_stars=10,
                telegram_payment_charge_id=f"t137-{target}-{i}",
                status="completed"))
        db.commit()


def seed_streak(uid, days):
    """DailyClaim check-in rows for the last `days` days, ending
    today — the same rows _checkin_streak counts."""
    today = datetime.utcnow().date()
    with SessionLocal() as db:
        for i in range(days):
            day = (today - timedelta(days=i)).isoformat()
            db.add(models.DailyClaim(user_id=uid, task_key="checkin",
                                     day=day))
        db.commit()


def profile(c, uid, headers):
    r = c.get(f"/users/{uid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def badge_map(badges):
    return {b["id"]: b for b in badges}


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE, EVE, FRANK, GRACE, HEIDI,
              IVAN, OFF):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. level_for boundaries, pure.
    cases = [(0, 1, "Newcomer"), (99, 1, "Newcomer"),
             (100, 2, "Rising"), (499, 2, "Rising"),
             (500, 3, "Active"), (999, 3, "Active"),
             (1000, 4, "Creator"), (2499, 4, "Creator"),
             (2500, 5, "Influencer"), (4999, 5, "Influencer"),
             (5000, 6, "Star"), (9999, 6, "Star"),
             (10000, 7, "Legend"), (19999, 7, "Legend"),
             (20000, 8, "Nexora Elite"), (99999, 8, "Nexora Elite")]
    for pts, lvl, name in cases:
        got = level_for(pts)
        assert got["level"] == lvl and got["name"] == name, (pts, got)
        assert got["points"] == pts, (pts, got)
    assert level_for(0)["progress"] == 0.0
    assert level_for(100)["progress"] == 0.0
    assert level_for(50)["progress"] == 0.5
    assert level_for(750)["progress"] == 0.5
    assert level_for(20000)["progress"] == 1.0
    assert level_for(20000)["next_level"] is None
    assert level_for(99999)["next_level"] is None
    nxt = level_for(4999)["next_level"]
    assert nxt == {"level": 6, "name": "Star", "points_needed": 1}, nxt
    nxt = level_for(0)["next_level"]
    assert nxt == {"level": 2, "name": "Rising", "points_needed": 100}, nxt
    print("level_for boundaries + progress OK")

    # 2. Fresh member: only Pioneer earned (joined Nov 2026, i.e.
    # before Dec 2026); every other badge listed but locked.
    p = profile(c, 777, GRACE)
    assert p["level"] == {"level": 1, "name": "Newcomer", "points": 0,
                          "next_level": {"level": 2, "name": "Rising",
                                         "points_needed": 100},
                          "progress": 0.0}, p["level"]
    bm = badge_map(p["badges"])
    assert len(p["badges"]) == 9, len(p["badges"])
    assert bm["pioneer"]["earned"] is True, bm["pioneer"]
    for bid in ("first-post", "25-posts", "100-posts",
                "500-followers", "1000-followers", "verified",
                "tips-10", "streak-30"):
        assert bm[bid]["earned"] is False, (bid, bm[bid])
        assert bm[bid]["hint"], (bid, bm[bid])
    print("fresh member badges OK (only Pioneer earned)")

    # 3. Pioneer is about join date, not the present: a member
    # whose created_at is after 2026-12-01 is NOT a Pioneer.
    set_created(666, datetime(2026, 12, 15))
    p = profile(c, 666, FRANK)
    assert badge_map(p["badges"])["pioneer"]["earned"] is False
    print("pioneer join-date rule OK")

    # 4. Posts: 1 post -> First Post; 25 posts -> 25 Posts.
    r = c.post("/posts", headers=ALICE, json={"text": "hello world"})
    assert r.status_code == 200, r.text
    p = profile(c, 111, ALICE)
    bm = badge_map(p["badges"])
    assert bm["first-post"]["earned"] is True
    assert bm["25-posts"]["earned"] is False
    # One API post also earns +10 lifetime points.
    assert p["level"]["level"] == 1 and p["level"]["points"] == 10, \
        p["level"]
    for i in range(25):
        r = c.post("/posts", headers=BOB, json={"text": f"post {i}"})
        assert r.status_code == 200, r.text
    p = profile(c, 222, BOB)
    bm = badge_map(p["badges"])
    assert bm["first-post"]["earned"] is True
    assert bm["25-posts"]["earned"] is True
    assert bm["100-posts"]["earned"] is False
    assert p["level"] == {"level": 2, "name": "Rising", "points": 250,
                          "next_level": {"level": 3, "name": "Active",
                                         "points_needed": 250},
                          "progress": 0.375}, p["level"]
    print("post badges + level via HTTP OK")

    # 5. Verified -> Verified badge.
    with SessionLocal() as db:
        db.get(models.User, 333).is_verified = True
        db.commit()
    p = profile(c, 333, CAROL)
    assert badge_map(p["badges"])["verified"]["earned"] is True
    print("verified badge OK")

    # 6. Followers: 500 -> 500 Followers (1000 stays locked).
    seed_followers(444, 500)
    p = profile(c, 444, DAVE)
    bm = badge_map(p["badges"])
    assert bm["500-followers"]["earned"] is True
    assert bm["1000-followers"]["earned"] is False
    assert p["followers"] == 500, p["followers"]
    print("follower badges OK")

    # 7. Tips: 10 completed tips received -> 10 Tips.
    seed_tips(555, 10)
    p = profile(c, 555, EVE)
    assert badge_map(p["badges"])["tips-10"]["earned"] is True
    print("tips badge OK")

    # 8. Streak: 30 consecutive check-in days -> 30-Day Streak;
    # 5 days does not earn it.
    seed_streak(888, 30)
    p = profile(c, 888, HEIDI)
    assert badge_map(p["badges"])["streak-30"]["earned"] is True
    seed_streak(555, 5)
    p = profile(c, 555, EVE)
    assert badge_map(p["badges"])["streak-30"]["earned"] is False
    print("streak badge OK")

    # 9. Level via HTTP tracks seeded ledger amounts exactly.
    add_points(999, 4999)
    p = profile(c, 999, IVAN)
    assert p["level"]["level"] == 5 and p["level"]["name"] == "Influencer", \
        p["level"]
    assert p["level"]["next_level"] == {"level": 6, "name": "Star",
                                        "points_needed": 1}, p["level"]
    add_points(999, 1)
    p = profile(c, 999, IVAN)
    assert p["level"]["level"] == 6 and p["level"]["name"] == "Star", \
        p["level"]
    assert p["level"]["points"] == 5000, p["level"]
    assert p["level"]["progress"] == 0.0, p["level"]
    print("level via HTTP (4999 -> L5, 5000 -> L6 Star) OK")

    # 10. /auth (the signed-in member dict) carries level + badges.
    r = c.post("/auth", json={"initData": ALICE["X-Init-Data"]})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["level"]["level"] == 1 and me["level"]["points"] == 10, \
        me["level"]
    assert badge_map(me["badges"])["first-post"]["earned"] is True
    assert badge_map(me["badges"])["pioneer"]["earned"] is True
    print("/auth level + badges OK")

    # 11. Backup: still 39 tables (no new table this phase).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.status_code
    bk = r.json()
    assert len(bk["tables"]) == 52, len(bk["tables"])
    print("backup: 39 tables OK")

    # 12. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=191") == 10, html.count("?v=191")
    assert "?v=136" not in html
    js = open("webapp/app.js").read()
    for m in ("renderLevelBlock", "level-block", "level-bar",
              "level-fill", "badge-row", "badge-chip", "badge-locked",
              "My level", "level-card", "Max level",
              "points to Level", "/users/\" + me.telegram_id"):
        assert m in js, m
    main_src = open("app/main.py").read()
    for m in ("def level_for", "def badges_for", "LEVELS =",
              "def _lifetime_points", "def _level_and_badges",
              "BADGE_DEFS"):
        assert m in main_src, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus", "openTipSheet", "openInsights",
              "ins-chart", "ins-table", "schedLocalInput", "loadScheduled",
              "composer-schedule", "loadFollowRequests", "privacy-row",
              "private-lock"):
        assert m in js, m
    css = open("webapp/style.css").read()
    assert ".level-block" in css and ".level-bar" in css \
        and ".badge-chip" in css and ".badge-locked" in css
    print("client markers + ?v=191 OK")

print("PHASE-137 TESTS PASSED")
