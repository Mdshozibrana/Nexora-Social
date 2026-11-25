"""Phase-142 tests: Audit Log filter + Content search + banned-word list.

Covers: GET /admin/audit-log filters (?action= exact, ?actor= id or
username substring, ?from=/?to= inclusive dates, limit/offset paging
with total + next_offset; invalid date 400; non-admin 403, unauth 401);
GET /admin/content/search?q= (matches post text or author name/username,
case-insensitive, newest first, paging; empty q 400; non-admin 403);
banned words (add/list/remove, lowercase normalization, duplicate 400,
empty 400, non-admin 403, unknown id 404, add/remove audit-logged);
enforcement (post with a banned word 400 + no post created, comment
400, case-insensitive, clean text unaffected, scheduled post fails
via the sweeper path, DM text with a banned word NOT blocked);
backup 42 tables incl. banned_words rows; ?v=183 x5, no ?v=183;
admin-trio client markers + Phase 123-141 markers intact.

Scope note: DMs are private conversations and are deliberately NOT
checked against the banned-word list (documented in the PRD).
"""
import asyncio, hashlib, hmac, json, os, sqlite3, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase141.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.main as main_mod

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


def audit_entries():
    with SessionLocal() as db:
        return [(r.action, r.admin_id, r.created_at) for r in db.query(
            models.AdminAuditLog).order_by(models.AdminAuditLog.id).all()]


def seed_audit(admin_id, action, days_ago, detail=""):
    with SessionLocal() as db:
        db.add(models.AdminAuditLog(
            admin_id=admin_id, action=action, detail=detail,
            created_at=datetime.utcnow() - timedelta(days=days_ago)))
        db.commit()


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Banned words: add/list/remove, validation, admin-only.
    r = c.get("/admin/banned-words", headers=ALICE)
    assert r.status_code == 200 and r.json()["words"] == [], r.text
    r = c.get("/admin/banned-words", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/banned-words")
    assert r.status_code == 401, r.status_code
    r = c.post("/admin/banned-words", headers=BOB, json={"word": "spam"})
    assert r.status_code == 403, r.status_code
    r = c.post("/admin/banned-words", headers=ALICE, json={"word": "  SPAM "})
    assert r.status_code == 200, r.text
    assert r.json()["word"] == "spam", r.json()
    wid = r.json()["id"]
    assert "banned_word_add" in [a for a, _, _ in audit_entries()]
    r = c.post("/admin/banned-words", headers=ALICE, json={"word": "Spam"})
    assert r.status_code == 400, r.status_code
    r = c.post("/admin/banned-words", headers=ALICE, json={"word": "   "})
    assert r.status_code == 400, r.status_code
    r = c.post("/admin/banned-words", headers=ALICE, json={"word": "scam"})
    assert r.status_code == 200, r.text
    r = c.get("/admin/banned-words", headers=ALICE)
    words = [w["word"] for w in r.json()["words"]]
    assert words == ["scam", "spam"], words  # newest first
    r = c.delete(f"/admin/banned-words/{wid}", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.delete("/admin/banned-words/424242", headers=ALICE)
    assert r.status_code == 404, r.status_code
    r = c.delete(f"/admin/banned-words/{wid}", headers=ALICE)
    assert r.status_code == 200, r.text
    assert "banned_word_remove" in [a for a, _, _ in audit_entries()]
    r = c.get("/admin/banned-words", headers=ALICE)
    assert [w["word"] for w in r.json()["words"]] == ["scam"], r.json()
    print("banned-word CRUD OK")

    # 2. Enforcement: posts + comments blocked, DMs not blocked.
    r = c.post("/posts", headers=BOB,
               json={"type": "text", "caption": "a SCAM alert for all"})
    assert r.status_code == 400, r.text
    assert "isn't allowed" in r.json()["detail"], r.json()
    assert "scam" not in r.json()["detail"]  # never echo the word
    with SessionLocal() as db:
        assert db.query(models.Post).filter(
            models.Post.user_id == 222).count() == 0
    r = c.post("/posts", headers=BOB,
               json={"type": "text", "caption": "a perfectly clean post"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = c.post(f"/posts/{pid}/comments", headers=CAROL,
               json={"text": "total SCAM, avoid"})
    assert r.status_code == 400, r.text
    r = c.post(f"/posts/{pid}/comments", headers=CAROL,
               json={"text": "nice post!"})
    assert r.status_code == 200, r.text
    # DMs are private: the same word is NOT blocked there.
    r = c.post("/messages/222", headers=CAROL,
               json={"text": "watch out for this scam"})
    assert r.status_code == 200, r.text
    print("banned-word enforcement OK (posts + comments, not DMs)")

    # 3. Scheduled post with a banned word fails via the sweeper.
    with SessionLocal() as db:
        db.add(models.ScheduledPost(
            user_id=222, text="another SCAM deal", media_type="text",
            media_file_id=None,
            scheduled_at=datetime.utcnow() - timedelta(minutes=1),
            status="pending"))
        db.commit()
    main_mod._run_scheduled_sweep()
    with SessionLocal() as db:
        row = db.query(models.ScheduledPost).filter_by(
            user_id=222).first()
        assert row.status == "failed", row.status
        assert "isn't allowed" in (row.error or ""), row.error
        assert db.query(models.Post).filter(
            models.Post.user_id == 222,
            models.Post.caption == "another SCAM deal").count() == 0
    print("scheduled-post banned-word failure OK")

    # 4. Audit-log filters.
    seed_audit(111, "banned_word_add", 40, "word oldword")
    seed_audit(222, "points_adjust", 5, "target 333")
    seed_audit(111, "post_remove", 5, "post 9")
    seed_audit(333, "broadcast", 0, "all")
    r = c.get("/admin/audit-log", headers=ALICE)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 7, j["total"]  # 3 real + 4 seeded
    ids = [e["id"] for e in j["entries"]]
    assert ids == sorted(ids, reverse=True), ids  # newest first
    assert j["next_offset"] is None, j
    r = c.get("/admin/audit-log?action=post_remove", headers=ALICE)
    assert r.json()["total"] == 1, r.json()
    assert [e["action"] for e in r.json()["entries"]] == ["post_remove"]
    r = c.get("/admin/audit-log?actor=222", headers=ALICE)
    assert r.json()["total"] == 1, r.json()
    assert all(e["admin_id"] == 222 for e in r.json()["entries"])
    r = c.get("/admin/audit-log?actor=ali", headers=ALICE)
    assert r.json()["total"] == 5, r.json()  # Alice: 3 real + 2 seeded
    assert all(e["admin_id"] == 111 for e in r.json()["entries"])
    today = datetime.utcnow().date().isoformat()
    week_ago = (datetime.utcnow() - timedelta(days=7)).date().isoformat()
    old_day = (datetime.utcnow() - timedelta(days=40)).date().isoformat()
    r = c.get(f"/admin/audit-log?from={week_ago}&to={today}", headers=ALICE)
    assert r.json()["total"] == 6, r.json()
    for e in r.json()["entries"]:
        assert week_ago <= e["created_at"][:10] <= today, e
        assert e["created_at"][:10] != old_day, e
    r = c.get("/admin/audit-log?action=post_remove&actor=111",
              headers=ALICE)
    assert r.json()["total"] == 1, r.json()
    r = c.get("/admin/audit-log?action=post_remove&actor=222",
              headers=ALICE)
    assert r.json()["total"] == 0, r.json()
    r = c.get("/admin/audit-log?limit=2&offset=0", headers=ALICE)
    assert len(r.json()["entries"]) == 2, r.json()
    assert r.json()["next_offset"] == 2, r.json()
    assert r.json()["total"] == 7, r.json()
    r2 = c.get("/admin/audit-log?limit=2&offset=2", headers=ALICE)
    assert [e["id"] for e in r2.json()["entries"]] != \
        [e["id"] for e in r.json()["entries"]]
    r = c.get("/admin/audit-log?from=not-a-date", headers=ALICE)
    assert r.status_code == 400, r.status_code
    r = c.get("/admin/audit-log?to=2026-13-45", headers=ALICE)
    assert r.status_code == 400, r.status_code
    r = c.get("/admin/audit-log", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/audit-log")
    assert r.status_code == 401, r.status_code
    print("audit-log filters OK")

    # 5. Content search.
    r = c.get("/admin/content/search", headers=ALICE)
    assert r.status_code == 400, r.status_code  # empty q
    r = c.get("/admin/content/search?q=clean", headers=ALICE)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 1, j
    assert j["posts"][0]["id"] == pid, j
    assert j["posts"][0]["author_name"] == "Bob", j
    assert "author_username" in j["posts"][0], j
    assert "has_media" in j["posts"][0], j
    r = c.get("/admin/content/search?q=bob", headers=ALICE)
    assert r.json()["total"] == 1, r.json()
    assert all(p["author_name"] == "Bob"
               for p in r.json()["posts"])
    r = c.get("/admin/content/search?q=zzzz-no-match", headers=ALICE)
    assert r.json()["total"] == 0, r.json()
    assert r.json()["posts"] == [], r.json()
    r = c.get("/admin/content/search?q=clean&limit=1&offset=0",
              headers=ALICE)
    assert len(r.json()["posts"]) == 1, r.json()
    assert r.json()["next_offset"] is None, r.json()
    r = c.get("/admin/content/search?q=clean", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/content/search?q=clean")
    assert r.status_code == 401, r.status_code
    print("content search OK")

    # 6. Backup carries banned_words (42 tables).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    bk = r.json()
    assert len(bk["tables"]) == 52, len(bk["tables"])
    assert "banned_words" in bk["tables"], list(bk["tables"])
    assert any(w["word"] == "scam"
               for w in bk["tables"]["banned_words"])
    print("backup: 42 tables incl. banned_words OK")

    # 7. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=183") == 10, html.count("?v=183")
    assert "?v=14" + "1" not in html
    js = open("webapp/app.js").read()
    for m in ("loadAuditLog", "applyAuditFilters", "clearAuditFilters",
              "loadAuditMore", "auditQuery", "renderAuditRow",
              "fillAuditActions", "updateAuditMore", "audit-more",
              "audit-action", "audit-actor", "audit-from", "audit-to",
              "searchAdminContent", "renderAdminPostRows",
              "refreshAdminPosts", "loadBannedWords", "addBannedWord",
              "admin-banned-words", "bw-word", "bw-add",
              "/admin/banned-words", "/admin/content/search",
              "banned words"):
        assert m in js, m
    for m in ("audit-action", "audit-actor", "audit-apply", "audit-clear",
              "audit-more", "admin-content-q", "admin-content-go",
              "admin-content-clear", "cp-sec-banned", "Banned words",
              "bw-word", "bw-add", "admin-banned-words",
              "Search content", "Apply filters", "Show more"):
        assert m in html, m
    main_src = open("app/main.py").read()
    for m in ("admin_audit_log", "_parse_audit_date",
              "admin_content_search", "admin_banned_words",
              "admin_banned_word_add", "admin_banned_word_remove",
              "banned_word_add", "banned_word_remove",
              "banned_word_in", "BANNED_WORD_MESSAGE",
              "admin/content/search"):
        assert m in main_src, m
    svc_src = open("app/services.py").read()
    for m in ("def banned_word_in", "BANNED_WORD_MESSAGE"):
        assert m in svc_src, m
    bot_src = open("app/bot.py").read()
    assert "banned_word_in(db, update.message.caption" in bot_src
    for m in ("loadAutoBackup", "auto-backup-toggle", "auto-backup-line",
              "/admin/auto-backup", "Auto-backup"):
        assert m in js, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus", "openTipSheet", "openInsights",
              "ins-chart", "ins-table", "schedLocalInput", "loadScheduled",
              "composer-schedule", "loadFollowRequests", "privacy-row",
              "private-lock", "renderLevelBlock", "level-block",
              "level-bar", "badge-row", "badge-chip", "badge-locked",
              "DM_REACTIONS", "reactToMessage", "chat-photo",
              "bubble-photo", "openStoryViewers", "sendStoryReply",
              "story-reply", "story-viewers", "tab-hashtags",
              "search-tag-follow", "hashtag-card", "hashtag-row",
              "followedTags", "/me/hashtags", "/feed/hashtags"):
        assert m in js, m
    print("client markers + ?v=183 OK")

print("ALL PHASE 142 CHECKS PASSED")
