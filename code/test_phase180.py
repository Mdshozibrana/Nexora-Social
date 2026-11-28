"""Phase 180 tests: Jobs & economy — audit H9/H14/M12/M13/M22/M23/M24/M26.

H9 — scheduled sweeper crash-safe: claim-then-publish, a crashed
  "publishing" row is ADOPTED (its post exists — no duplicate, no
  second +10) or published (no post exists); sync_mentions() and
  register_post() throwing after commit still end posted, once.
M12 — auto-backup: no double-send after a crash (stamp-first),
  manual backup recency suppresses the first auto send, failed
  build/send restores the previous stamp and retries.
M13 — loop-level failures (sweep dies, auto-backup loop dies)
  leave admin-visible security-log rows, not just server logs.
H14 — /ads/shown answers 410 and creates no AdEvent while no ad
  provider is live; the adwatch task reports available=False and
  is never claimable.
M22 — daily boundary is Asia/Dhaka: the audit's 05:00-Dhaka-Mon +
  07:00-Dhaka-Tue check-ins keep the streak (UTC dates of those
  two instants are two days apart).
M23 — leaderboard ranks by lifetime points: a cashed-out creator
  keeps rank 1; ties share a rank.
M24 — self-like/self-comment do not count toward react6/comment5;
  follow3 counts distinct targets and unfollow+re-follow does not
  re-farm.
M26 — parallel double-claim: one 200 + one clean 400, points
  awarded once; the IntegrityError path answers 400 too.
Plain script (run.sh runs it with python directly).
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase180.db"
os.environ["ADMIN_IDS"] = "1809"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
import app.main as main_mod  # noqa: E402
from app.main import app, _BACKUP_TABLES, _run_scheduled_sweep  # noqa: E402
from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402

DHAKA = ZoneInfo("Asia/Dhaka")


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(1801, "Alice", "alice180")
BOB = H(1802, "Bob", "bob180")
CAROL = H(1803, "Carol", "carol180")
DAVE = H(1804, "Dave", "dave180")
EVE = H(1805, "Eve", "eve180")
FRANK = H(1806, "Frank", "frank180")
GRACE = H(1807, "Grace", "grace180")
HEIDI = H(1808, "Heidi", "heidi180")
ADMIN = H(1809, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
MAIN = open(os.path.join(ROOT, "code/app/main.py")).read()


def tasks(c, h):
    return {t["key"]: t
            for t in c.get("/me/tasks", headers=h).json()["tasks"]}


def balance(c, h):
    return c.get("/me/points", headers=h).json()["balance"]


def post_points(uid):
    with SessionLocal() as db:
        rows = db.query(models.PointsLedger).filter_by(
            user_id=uid, reason="post").all()
        return sum(r.amount for r in rows)


def post_count(uid):
    with SessionLocal() as db:
        return db.query(models.Post).filter_by(
            user_id=uid, is_deleted=False).count()


def sched_row(row_id):
    with SessionLocal() as db:
        r = db.get(models.ScheduledPost, row_id)
        return (r.status, r.posted_post_id, r.error) if r else None


def add_due_row(uid, text, minutes_ago=1):
    with SessionLocal() as db:
        db.add(models.ScheduledPost(
            user_id=uid, text=text,
            scheduled_at=datetime.utcnow() - timedelta(minutes=minutes_ago)))
        db.commit()
        return db.query(models.ScheduledPost).filter_by(
            user_id=uid, text=text).one().id


def set_row(row_id, **kw):
    with SessionLocal() as db:
        r = db.get(models.ScheduledPost, row_id)
        for k, v in kw.items():
            setattr(r, k, v)
        db.commit()


def set_last_run(days_ago):
    with SessionLocal() as db:
        main_mod._set_app_setting(
            db, "auto_backup_last_run",
            (datetime.utcnow() - timedelta(days=days_ago)).isoformat())
        db.commit()


def get_setting(key):
    with SessionLocal() as db:
        row = db.get(models.AppSetting, key)
        return row.value if row is not None else None


def audit_actions():
    with SessionLocal() as db:
        return [r.action for r in db.query(
            models.AdminAuditLog).order_by(models.AdminAuditLog.id).all()]


def security_kinds():
    with SessionLocal() as db:
        return [r.kind for r in db.query(
            models.SecurityEvent).order_by(models.SecurityEvent.id).all()]


def security_details(kind="server_error"):
    with SessionLocal() as db:
        return [r.detail for r in db.query(models.SecurityEvent).filter_by(
            kind=kind).order_by(models.SecurityEvent.id).all()]


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE, EVE, FRANK, GRACE, HEIDI, ADMIN):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200, r.text

    # --- 1. H9a: normal sweep, then a crash AFTER the post commit --
    # The row is claimed ("publishing") before register_post; a
    # restart that lands after the post commit but before the row
    # update must ADOPT the post on the next sweep — exactly one
    # post, exactly +10, row posted with the same post id.
    rid = add_due_row(1801, "crash window post")
    n0, p0 = post_count(1801), post_points(1801)
    _run_scheduled_sweep()
    st, pid, err = sched_row(rid)
    assert st == "posted" and err is None and isinstance(pid, int), (st, pid)
    assert post_count(1801) == n0 + 1 and post_points(1801) == p0 + 10
    # Simulate the crash: row back to "publishing", link wiped —
    # as if the process died after register_post() committed.
    set_row(rid, status="publishing", posted_post_id=None)
    _run_scheduled_sweep()
    st2, pid2, err2 = sched_row(rid)
    assert st2 == "posted" and pid2 == pid, (st2, pid2)
    assert post_count(1801) == n0 + 1, "adoption must not republish"
    assert post_points(1801) == p0 + 10, "adoption must not re-pay"
    _run_scheduled_sweep()
    assert post_count(1801) == n0 + 1 and post_points(1801) == p0 + 10
    print("H9a crash-after-commit adopted, no duplicate post/points OK")

    # --- 2. H9b: crash BEFORE register_post commits -----------------
    # A "publishing" row with no post at all is published for real
    # on the next sweep — exactly once.
    rid2 = add_due_row(1801, "crash before publish")
    set_row(rid2, status="publishing")
    n0, p0 = post_count(1801), post_points(1801)
    _run_scheduled_sweep()
    st, pid, err = sched_row(rid2)
    assert st == "posted" and isinstance(pid, int), (st, pid)
    assert post_count(1801) == n0 + 1 and post_points(1801) == p0 + 10
    print("H9b crash-before-publish publishes exactly once OK")

    # --- 3. H9c: sync_mentions() throws after the post is live ----
    # The old code failed the row (live post + failed row). Now the
    # mention failure is best-effort: the row still posts.
    real_sync = main_mod.sync_mentions

    def boom(*a, **k):
        raise RuntimeError("mentions down")

    main_mod.sync_mentions = boom
    try:
        rid3 = add_due_row(1801, "mentions down post")
        n0, p0 = post_count(1801), post_points(1801)
        _run_scheduled_sweep()
        st, pid, err = sched_row(rid3)
        assert st == "posted" and isinstance(pid, int), (st, err)
        assert post_count(1801) == n0 + 1
        assert post_points(1801) == p0 + 10
    finally:
        main_mod.sync_mentions = real_sync
    print("H9c sync_mentions failure still posts (no live+failed) OK")

    # --- 4. H9d: register_post() throws AFTER committing -----------
    # The post + points are committed, then the crash hits: the
    # sweep must adopt, not fail and not duplicate.
    real_register = main_mod.register_post

    def crashy_register(db, *a, **k):
        post, first, qualified = real_register(db, *a, **k)
        raise RuntimeError("restart mid-publish")

    main_mod.register_post = crashy_register
    try:
        rid4 = add_due_row(1801, "register crash post")
        n0, p0 = post_count(1801), post_points(1801)
        _run_scheduled_sweep()
        st, pid, err = sched_row(rid4)
        assert st == "posted" and isinstance(pid, int), (st, err)
        assert post_count(1801) == n0 + 1, "register crash must not duplicate"
        assert post_points(1801) == p0 + 10, "register crash must not re-pay"
    finally:
        main_mod.register_post = real_register
    print("H9d register_post crash-after-commit adopted OK")

    # --- 5. M12a: due logic incl. manual recency --------------------
    with SessionLocal() as db:
        db.query(models.AdminAuditLog).delete()
        row = db.get(models.AppSetting, "auto_backup_last_run")
        if row is not None:
            db.delete(row)
        db.commit()
    with SessionLocal() as db:
        assert main_mod._auto_backup_due(db) is True  # never run, no manual
    # A manual backup minutes ago suppresses the first auto send.
    with SessionLocal() as db:
        db.add(models.AdminAuditLog(admin_id=1809, action="backup_download",
                                    detail="manual"))
        db.commit()
    with SessionLocal() as db:
        assert main_mod._auto_backup_due(db) is False, \
            "manual backup minutes ago must suppress the auto send"
        assert main_mod._auto_backup_next_due(db) > datetime.utcnow()
    # A manual backup 8 days ago does not suppress it.
    with SessionLocal() as db:
        r = db.query(models.AdminAuditLog).filter_by(
            action="backup_download").one()
        r.created_at = datetime.utcnow() - timedelta(days=8)
        db.commit()
    set_last_run(8)
    with SessionLocal() as db:
        assert main_mod._auto_backup_due(db) is True
    print("M12a due logic + manual recency OK")

    # --- 6. M12b: no double-send, failed send retries --------------
    sent_docs = []

    async def fake_send(chat_id, filename, data, caption=""):
        sent_docs.append((chat_id, filename, data, caption))
        return True

    set_last_run(8)
    # Simulate the crash window: a run already stamped its run
    # (send done, process died before the success record) — the
    # next hourly check must NOT re-send the same backup.
    prev = asyncio.run(asyncio.to_thread(
        main_mod._stamp_auto_backup_attempt))
    assert prev is not None
    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=fake_send))
    assert ok is False and len(sent_docs) == 0, \
        "a stamped run must not re-send after a crash"
    # Restore the pre-crash stamp and run for real: one send, and
    # a second immediate check sends nothing more.
    asyncio.run(asyncio.to_thread(
        main_mod._restore_auto_backup_stamp, prev))
    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=fake_send))
    assert ok is True and len(sent_docs) == 1, (ok, len(sent_docs))
    assert sent_docs[0][0] == 1809, sent_docs[0][0]
    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=fake_send))
    assert ok is False and len(sent_docs) == 1
    # A failed send leaves last_run alone and retries fine.
    set_last_run(8)
    before = get_setting("auto_backup_last_run")

    async def failing_send(chat_id, filename, data, caption=""):
        return False

    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=failing_send))
    assert ok is False and len(sent_docs) == 1
    assert get_setting("auto_backup_last_run") == before
    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=fake_send))
    assert ok is True and len(sent_docs) == 2
    # A BUILD crash: nothing sent, stamp restored, admin-visible.
    set_last_run(8)
    before = get_setting("auto_backup_last_run")
    real_build = main_mod._build_auto_backup

    def boom_build():
        raise RuntimeError("disk full")

    main_mod._build_auto_backup = boom_build
    try:
        ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=fake_send))
    finally:
        main_mod._build_auto_backup = real_build
    assert ok is False and len(sent_docs) == 2
    assert get_setting("auto_backup_last_run") == before
    assert "auto_backup_failed" in audit_actions(), audit_actions()
    assert "server_error" in security_kinds(), security_kinds()
    print("M12b no double-send + failed send/build restore + retry OK")

    # --- 7. M13: loop-level failures are admin-visible -------------
    orig_sleep = asyncio.sleep
    # Scheduled sweep loop: first sleep dies -> security row, then
    # the loop iterates and the second sleep cancels it for real.
    calls = {"n": 0}

    async def two_step_sleep(delay):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated DB outage")
        raise asyncio.CancelledError()

    main_mod.asyncio.sleep = two_step_sleep
    try:
        try:
            asyncio.run(main_mod._scheduled_posts_loop())
        except asyncio.CancelledError:
            pass
    finally:
        main_mod.asyncio.sleep = orig_sleep
    assert any("scheduled-posts sweep failed" in d
               for d in security_details()), security_details()
    calls["n"] = 0
    main_mod.asyncio.sleep = two_step_sleep
    try:
        try:
            asyncio.run(main_mod._auto_backup_loop())
        except asyncio.CancelledError:
            pass
    finally:
        main_mod.asyncio.sleep = orig_sleep
    assert any("auto-backup loop failed" in d
               for d in security_details()), security_details()
    print("M13 loop failures leave security-log rows OK")

    # --- 8. H14: ad-watch paused ------------------------------------
    r = c.post("/ads/shown", headers=CAROL)
    assert r.status_code == 410, (r.status_code, r.text)
    assert r.json()["detail"] == "Ads are not available right now"
    with SessionLocal() as db:
        assert db.query(models.AdEvent).filter_by(
            user_id=1803).count() == 0, "410 must create no AdEvent"
    t = tasks(c, CAROL)
    assert t["adwatch"]["progress"] == 0, t["adwatch"]
    assert t["adwatch"]["claimable"] is False, t["adwatch"]
    assert t["adwatch"]["available"] is False, t["adwatch"]
    r = c.post("/me/tasks/adwatch/claim", headers=CAROL)
    assert r.status_code == 400, r.text
    assert balance(c, CAROL) == 0, "no points from a paused task"
    assert 't.key === "adwatch" && t.available === false' in JS
    assert 'btn.textContent = "No ad available";' in JS
    assert "async function showTaskAd(btn)" in JS, \
        "showTaskAd stays for a provider's return"
    assert 'await api("/ads/shown", { method: "POST" })' in JS
    assert "ADS_PROVIDER_LIVE" in MAIN
    print("H14 /ads/shown 410 + task unavailable + no points OK")

    # --- 9. M22: Dhaka daily boundary -------------------------------
    day, day_start = main_mod._today()
    dhaka_now = datetime.now(DHAKA)
    assert day == dhaka_now.date().isoformat(), (day, dhaka_now)
    expect_start = dhaka_now.replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc).replace(tzinfo=None)
    assert day_start == expect_start, (day_start, expect_start)
    # The audit's case: 05:00 Dhaka Mon + 07:00 Dhaka Tue. Those
    # two instants are TWO days apart in UTC (Sun 23:00 + Tue
    # 01:00) but ONE day apart in Dhaka — the old UTC boundary
    # reset the streak; Dhaka keeps it.
    dhaka_tue = dhaka_now.date()
    dhaka_mon = dhaka_tue - timedelta(days=1)
    mon_instant = datetime.combine(dhaka_mon, dtime(5, 0), tzinfo=DHAKA)
    tue_instant = datetime.combine(dhaka_tue, dtime(7, 0), tzinfo=DHAKA)
    assert (tue_instant.astimezone(timezone.utc).date()
            - mon_instant.astimezone(timezone.utc).date()).days == 2
    assert (dhaka_tue - dhaka_mon).days == 1
    with SessionLocal() as db:
        for d in (dhaka_mon, dhaka_tue):
            db.add(models.DailyClaim(user_id=1803, task_key="checkin",
                                     day=d.isoformat()))
        db.commit()
        assert main_mod._checkin_streak(db, 1803) == 2, \
            "consecutive Dhaka days must streak"
    # A live check-in claim lands on the Dhaka day and streaks.
    r = c.post("/me/tasks/checkin/claim", headers=DAVE)
    assert r.status_code == 200, r.text
    assert r.json()["points_awarded"] == 20
    t = tasks(c, DAVE)
    assert t["checkin"]["streak"] == 1
    r = c.post("/me/tasks/checkin/claim", headers=DAVE)
    assert r.status_code == 400, "second check-in same Dhaka day refused"
    print("M22 Dhaka boundary + streak keeps consecutive local days OK")

    # --- 10. M23: leaderboard ranks by lifetime points -------------
    with SessionLocal() as db:
        for uid, lifetime, bal in ((1810, 500, 50), (1811, 300, 300),
                                   (1812, 300, 300), (1813, 100, 100),
                                   (1814, 0, 0)):
            u = db.get(models.User, uid)
            if u is None:
                u = models.User(telegram_id=uid, first_name=f"Board{uid}")
                db.add(u)
            u.points_balance = bal
            if lifetime:
                db.add(models.PointsLedger(user_id=uid, amount=lifetime,
                                           reason="post"))
        ned = db.get(models.User, 1815)
        if ned is None:
            ned = models.User(telegram_id=1815, first_name="Ned")
            db.add(ned)
        ned.is_banned = True
        ned.points_balance = 9999
        db.add(models.PointsLedger(user_id=1815, amount=9999,
                                   reason="post"))
        db.commit()
    board = c.get("/leaderboard", headers=H(1814, "Mia")).json()
    leaders = board["leaders"]
    assert leaders[0]["telegram_id"] == 1810, leaders[0]
    assert leaders[0]["points"] == 500, leaders[0]
    assert leaders[0]["rank"] == 1, leaders[0]
    assert balance(c, H(1810, "Board1810")) == 50, \
        "rank 1 with a cashed-out balance of 50 proves lifetime ranking"
    tied = [r for r in leaders if r["telegram_id"] in (1811, 1812)]
    assert len(tied) == 2 and {r["points"] for r in tied} == {300}
    assert {r["rank"] for r in tied} == {2}, tied
    leo = next(r for r in leaders if r["telegram_id"] == 1813)
    assert leo["points"] == 100 and leo["rank"] == 4, leo
    assert all(r["telegram_id"] != 1815 for r in leaders), \
        "banned members stay off the board"
    pts = [r["points"] for r in leaders]
    assert pts == sorted(pts, reverse=True)
    with SessionLocal() as db:
        above_zero = db.query(models.PointsLedger.user_id).filter(
            models.PointsLedger.amount > 0).distinct().count()
    # Every lifetime>0 member except the banned one sits above Mia.
    assert board["me"]["telegram_id"] == 1814
    assert board["me"]["rank"] == above_zero, board["me"]
    print("M23 leaderboard by lifetime points + shared tie rank OK")

    # --- 11. M24: self-activity excluded; follow3 cannot re-farm ---
    r = c.post("/posts", headers=GRACE,
               json={"type": "text", "caption": "grace own post"})
    assert r.status_code == 200, r.text
    own_id = r.json()["id"]
    r = c.post("/posts", headers=FRANK,
               json={"type": "text", "caption": "frank post"})
    assert r.status_code == 200, r.text
    frank_id = r.json()["id"]
    r = c.post(f"/posts/{own_id}/like", headers=GRACE)
    assert r.status_code == 200, r.text
    t = tasks(c, GRACE)
    assert t["react6"]["progress"] == 0, \
        f"liking your own post must not count: {t['react6']}"
    r = c.post(f"/posts/{frank_id}/like", headers=GRACE)
    assert r.status_code == 200, r.text
    assert tasks(c, GRACE)["react6"]["progress"] == 1
    r = c.post(f"/posts/{own_id}/comments", headers=GRACE,
               json={"text": "self comment"})
    assert r.status_code == 200, r.text
    t = tasks(c, GRACE)
    assert t["comment5"]["progress"] == 0, \
        f"commenting your own post must not count: {t['comment5']}"
    r = c.post(f"/posts/{frank_id}/comments", headers=GRACE,
               json={"text": "nice post"})
    assert r.status_code == 200, r.text
    assert tasks(c, GRACE)["comment5"]["progress"] == 1
    for uid in (1808, 1801, 1802):
        r = c.post(f"/users/{uid}/follow", headers=GRACE)
        assert r.status_code == 200, r.text
    t = tasks(c, GRACE)
    assert t["follow3"]["progress"] == 3 and t["follow3"]["claimable"] is True
    # Unfollow + re-follow the same person: still 3, not 4.
    r = c.post("/users/1801/follow", headers=GRACE)
    assert r.json()["following"] is False, r.json()
    r = c.post("/users/1801/follow", headers=GRACE)
    assert r.json()["following"] is True, r.json()
    t = tasks(c, GRACE)
    assert t["follow3"]["progress"] == 3, \
        f"unfollow+re-follow must not re-farm: {t['follow3']}"
    with SessionLocal() as db:
        assert db.query(models.TaskFollowEvent).filter_by(
            user_id=1807).count() == 3
    r = c.post("/users/1803/follow", headers=GRACE)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.query(models.TaskFollowEvent).filter_by(
            user_id=1807).count() == 4, "a 4th distinct target counts"
    # The card caps the displayed progress at the target (3).
    assert tasks(c, GRACE)["follow3"]["progress"] == 3
    r = c.post("/me/tasks/follow3/claim", headers=GRACE)
    assert r.json()["points_awarded"] == 10, r.json()
    r = c.post("/me/tasks/follow3/claim", headers=GRACE)
    assert r.status_code == 400
    print("M24 self-activity excluded + follow3 distinct + no re-farm OK")

    # --- 12. M26: double-claim race -> one 200 + one clean 400 -----
    # (a) Deterministic: the IntegrityError path. A claim row is
    # already in the DB while the pre-check is forced to pass —
    # the endpoint must answer the clean 400, not a 500, and
    # award nothing.
    day, _ = main_mod._today()
    with SessionLocal() as db:
        db.add(models.DailyClaim(user_id=1805, task_key="checkin",
                                 day=day))
        db.commit()
    real_state = main_mod._task_state

    def forced_state(db, user, task):
        return {"claimed": False, "claimable": True}

    main_mod._task_state = forced_state
    try:
        r = c.post("/me/tasks/checkin/claim", headers=EVE)
    finally:
        main_mod._task_state = real_state
    assert r.status_code == 400, (r.status_code, r.text)
    assert r.json()["detail"] == "Already claimed today", r.json()
    assert balance(c, EVE) == 0, "loser of the race gets no points"
    with SessionLocal() as db:
        assert db.query(models.DailyClaim).filter_by(
            user_id=1805, task_key="checkin").count() == 1
        assert db.query(models.PointsLedger).filter_by(
            user_id=1805).count() == 0
    # (b) Real parallel claims on one shared client.
    RACER = H(1820, "Racer")
    r = c.post("/auth", json={"initData": RACER["X-Init-Data"]})
    assert r.status_code == 200, r.text

    def attempt(_):
        return c.post("/me/tasks/checkin/claim", headers=RACER).status_code

    with ThreadPoolExecutor(max_workers=2) as ex:
        codes = sorted(ex.map(attempt, (0, 1)))
    assert codes == [200, 400], codes
    assert balance(c, RACER) == 20, "points awarded exactly once"
    print("M26 parallel double-claim 200+400, points once OK")

    # --- 13. Backup tables (52), markers, asset version ------------
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    bk = r.json()
    assert len(bk["tables"]) == 55, len(bk["tables"])
    assert "task_follow_events" in bk["tables"], list(bk["tables"])
    assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
    assert HTML.count("?v=208") == 10, HTML.count("?v=208")
    assert "?v=17" + "9" not in HTML
    for m in ("_find_adoptable_post", "ADS_PROVIDER_LIVE",
              "_stamp_auto_backup_attempt", "_last_manual_backup_at",
              "auto-backup loop failed", "scheduled-posts sweep failed",
              "_DHAKA_TZ", "TaskFollowEvent"):
        assert m in MAIN, m
    print("backup 52 tables + markers + ?v=208 OK")

print("PHASE 180 OK")
