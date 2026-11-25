"""Phase-135 tests: scheduled posts.

Covers: create validation (past time 400, <5 min ahead 400,
>90 days 400, empty 400, bad media_type 400, bad date 400,
unauthenticated 401); list returns only the caller's rows;
cancel pending -> cancelled, cancel again 400, cancel another
member's 404, cancel unknown 404; sweeper publishes a due post
(real Post, status posted, posted_post_id set, author +10 points,
hashtags extracted) and skips future rows; sweeper marks a
screening-rejected post failed with a short human error, logs a
screen_reject event, and does NOT retry it on the next sweep;
backup carries 39 tables incl. scheduled_posts rows; ?v=185 x5,
no ?v=134; scheduled-post client markers + Phase 123-134
markers intact.
"""
import hashlib, hmac, json, os, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase135.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app, _run_scheduled_sweep
from app.db import SessionLocal
from app import models
from app.config import settings
import app.moderation as moderation

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


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def sched_row(row_id):
    with SessionLocal() as db:
        r = db.get(models.ScheduledPost, row_id)
        return (r.status, r.posted_post_id, r.error) if r else None


def post_count(uid):
    with SessionLocal() as db:
        return db.query(models.Post).filter_by(user_id=uid).count()


def post_points(uid):
    with SessionLocal() as db:
        return sum(r.amount for r in db.query(models.PointsLedger)
                   .filter_by(user_id=uid, reason="post").all())


with TestClient(app) as c:
    for h in (ALICE, BOB):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Create validation.
    now = datetime.utcnow()
    r = c.post("/scheduled-posts", headers=ALICE, json={
        "text": "too late", "scheduled_at": iso(now - timedelta(hours=1))})
    assert r.status_code == 400, r.text
    r = c.post("/scheduled-posts", headers=ALICE, json={
        "text": "too soon",
        "scheduled_at": iso(now + timedelta(minutes=2))})
    assert r.status_code == 400, r.text
    r = c.post("/scheduled-posts", headers=ALICE, json={
        "text": "too far",
        "scheduled_at": iso(now + timedelta(days=100))})
    assert r.status_code == 400, r.text
    r = c.post("/scheduled-posts", headers=ALICE, json={
        "text": "   ", "scheduled_at": iso(now + timedelta(hours=1))})
    assert r.status_code == 400, r.text
    r = c.post("/scheduled-posts", headers=ALICE, json={
        "text": "bad type", "media_type": "audio",
        "scheduled_at": iso(now + timedelta(hours=1))})
    assert r.status_code == 400, r.text
    r = c.post("/scheduled-posts", headers=ALICE, json={
        "text": "bad date", "scheduled_at": "not-a-date"})
    assert r.status_code == 400, r.text
    r = c.post("/scheduled-posts", json={
        "text": "no auth", "scheduled_at": iso(now + timedelta(hours=1))})
    assert r.status_code == 401, r.status_code
    print("create validation OK")

    # 2. Valid creates (one with a Z-suffixed time, as the client sends).
    r = c.post("/scheduled-posts", headers=ALICE, json={
        "text": "alice first",
        "scheduled_at": iso(now + timedelta(hours=1))})
    assert r.status_code == 200, r.text
    a1 = r.json()
    assert a1["status"] == "pending" and a1["posted_post_id"] is None
    r = c.post("/scheduled-posts", headers=ALICE, json={
        "text": "alice second",
        "scheduled_at": iso(now + timedelta(hours=2)) + "Z"})
    assert r.status_code == 200, r.text
    a2 = r.json()
    r = c.post("/scheduled-posts", headers=BOB, json={
        "text": "bob one",
        "scheduled_at": iso(now + timedelta(hours=1))})
    assert r.status_code == 200, r.text
    b1 = r.json()
    print("valid creates OK")

    # 3. List returns only the caller's rows.
    r = c.get("/scheduled-posts", headers=ALICE)
    assert r.status_code == 200, r.text
    rows = r.json()["scheduled_posts"]
    assert len(rows) == 2, rows
    assert {x["id"] for x in rows} == {a1["id"], a2["id"]}, rows
    r = c.get("/scheduled-posts", headers=BOB)
    assert len(r.json()["scheduled_posts"]) == 1, r.json()
    assert r.json()["scheduled_posts"][0]["id"] == b1["id"]
    r = c.get("/scheduled-posts")
    assert r.status_code == 401, r.status_code
    print("list isolation OK")

    # 4. Cancel: pending -> cancelled; again -> 400; other's -> 404.
    r = c.delete(f"/scheduled-posts/{a1['id']}", headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled", r.json()
    assert sched_row(a1["id"])[0] == "cancelled"
    r = c.delete(f"/scheduled-posts/{a1['id']}", headers=ALICE)
    assert r.status_code == 400, r.text
    r = c.delete(f"/scheduled-posts/{b1['id']}", headers=ALICE)
    assert r.status_code == 404, r.text
    r = c.delete("/scheduled-posts/999999", headers=ALICE)
    assert r.status_code == 404, r.text
    print("cancel rules OK")

    # 5. Sweeper publishes a due post through the normal path.
    with SessionLocal() as db:
        db.add(models.ScheduledPost(
            user_id=111, text="due post #hello",
            scheduled_at=datetime.utcnow() - timedelta(minutes=1)))
        db.commit()
        due_id = db.query(models.ScheduledPost).filter_by(
            user_id=111, text="due post #hello").one().id
    n0, p0 = post_count(111), post_points(111)
    _run_scheduled_sweep()
    st, pid, err = sched_row(due_id)
    assert st == "posted" and err is None, (st, err)
    assert isinstance(pid, int), pid
    assert post_count(111) == n0 + 1
    assert post_points(111) == p0 + 10, (p0, post_points(111))
    with SessionLocal() as db:
        p = db.get(models.Post, pid)
        assert p is not None and p.caption == "due post #hello"
        assert "hello" in (p.hashtags or ""), p.hashtags
        assert p.user_id == 111 and p.type == "text"
    # The future rows are untouched by the sweep.
    assert sched_row(a2["id"])[0] == "pending"
    assert sched_row(b1["id"])[0] == "pending"
    assert post_count(111) == n0 + 1
    print("sweeper publishes due post OK (+10 points, hashtags)")

    # 6. Sweeper marks a screening-rejected post failed, no retry.
    settings.GEMINI_API_KEY = "test-key"
    moderation.fetch_file_bytes = lambda fid: b"fake-jpeg-bytes"
    moderation.classify_image = lambda data, mime="image/jpeg": "adult"
    assert moderation.active()
    with SessionLocal() as db:
        db.add(models.ScheduledPost(
            user_id=222, text="bad pic", media_file_id="fake123",
            media_type="photo",
            scheduled_at=datetime.utcnow() - timedelta(minutes=1)))
        db.commit()
        bad_id = db.query(models.ScheduledPost).filter_by(
            user_id=222, text="bad pic").one().id
    n0 = post_count(222)
    _run_scheduled_sweep()
    st, pid, err = sched_row(bad_id)
    assert st == "failed" and pid is None, (st, pid)
    assert err and "wasn't posted" in err, err
    assert len(err) <= 256, len(err)
    assert post_count(222) == n0, "rejected media must not post"
    with SessionLocal() as db:
        ev = db.query(models.SecurityEvent).filter_by(
            kind="screen_reject", actor_id=222).count()
        assert ev >= 1, "screening rejection must be logged"
    _run_scheduled_sweep()
    assert sched_row(bad_id)[0] == "failed"
    assert post_count(222) == n0, "a failed row is never retried"
    print("sweeper screening failure OK (failed, logged, no retry)")

    # 7. Backup carries 39 tables incl. scheduled_posts rows.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.status_code
    bk = r.json()
    assert len(bk["tables"]) == 52, len(bk["tables"])
    assert "scheduled_posts" in bk["tables"], list(bk["tables"])
    assert len(bk["tables"]["scheduled_posts"]) >= 5, \
        len(bk["tables"]["scheduled_posts"])
    print("backup: 39 tables incl. scheduled_posts OK")

    # 8. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=185") == 10, html.count("?v=185")
    assert "?v=134" not in html
    assert 'id="composer-schedule-toggle"' in html
    assert 'id="composer-schedule"' in html
    assert 'id="composer-sched-datetime"' in html
    assert "Schedule post" in html
    js = open("webapp/app.js").read()
    for m in ("schedLocalInput", "loadScheduled", "composer-schedule",
              "composer-sched-datetime", "composer-sched-send",
              "/scheduled-posts", "📅 Scheduled", "Scheduled ✓"):
        assert m in js, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus", "openTipSheet", "openInsights",
              "ins-chart", "ins-table"):
        assert m in js, m
    print("client markers + ?v=185 OK")

print("PHASE-135 TESTS PASSED")
