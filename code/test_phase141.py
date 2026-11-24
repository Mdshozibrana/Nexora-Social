"""Phase-141 tests: weekly auto-backup to admin Telegram.

Covers: GET /admin/auto-backup (admin-only status: enabled,
last_auto_backup_at, next_due_at; non-admin 403, unauth 401);
POST /admin/auto-backup toggle on/off (admin only, audit-logged);
due logic (never run -> due; 8 days ago -> due; 6 days ago ->
not due; disabled -> never due); a due run builds the full
backup (42 tables, same _backup_payload as Phase 107) and sends
it to the owner (ADMIN_IDS[0]) as a document, writes the audit
event auto_backup_send and stamps auto_backup_last_run; a second
immediate run is not due; a failed send (False, or raising)
logs a server_error security event + audit auto_backup_failed,
leaves last_run unchanged, and retries fine on the next check;
the auto run does NOT consume the manual backup 10/h budget
(10 manual downloads still succeed, the 11th hits 429);
backup-status reports last_auto_backup_at; ?v=170 x5;
auto-backup client markers + Phase 123-140 markers intact.

Survey note: settings live in the AppSetting key-value table
(keys auto_backup_enabled / auto_backup_last_run) — no new
table, backup stays at 42 tables. The owner is ADMIN_IDS[0].
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


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Status endpoint: admin-only, default ON, never run.
    r = c.get("/admin/auto-backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True, r.json()
    assert r.json()["last_auto_backup_at"] is None, r.json()
    assert r.json()["next_due_at"], r.json()
    r = c.get("/admin/auto-backup", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/auto-backup")
    assert r.status_code == 401, r.status_code
    print("auto-backup status endpoint OK")

    # 2. Toggle off/on (admin only; audit-logged).
    r = c.post("/admin/auto-backup", headers=ALICE,
               json={"enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False, r.json()
    assert r.json()["next_due_at"] is None, r.json()
    assert "auto_backup_disabled" in audit_actions(), audit_actions()
    r = c.get("/admin/auto-backup", headers=ALICE)
    assert r.json()["enabled"] is False, r.json()
    r = c.post("/admin/auto-backup", headers=BOB, json={"enabled": True})
    assert r.status_code == 403, r.status_code
    r = c.post("/admin/auto-backup", headers=ALICE, json={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True, r.json()
    assert "auto_backup_enabled" in audit_actions(), audit_actions()
    print("auto-backup toggle OK")

    # 3. Due logic, straight from the helpers.
    with SessionLocal() as db:
        assert main_mod._auto_backup_due(db) is True  # never run
    set_last_run(8)
    with SessionLocal() as db:
        assert main_mod._auto_backup_due(db) is True
    set_last_run(6)
    with SessionLocal() as db:
        assert main_mod._auto_backup_due(db) is False
        assert main_mod._auto_backup_next_due(db) > datetime.utcnow()
    with SessionLocal() as db:
        main_mod._set_app_setting(db, "auto_backup_enabled", "0")
        db.commit()
    set_last_run(8)
    with SessionLocal() as db:
        assert main_mod._auto_backup_due(db) is False  # disabled: never due
    with SessionLocal() as db:
        main_mod._set_app_setting(db, "auto_backup_enabled", "1")
        db.commit()
    print("due logic OK (never / 8d / 6d / disabled)")

    # 4. A due run sends the full backup to the owner.
    sent_docs = []

    async def fake_send(chat_id, filename, data, caption=""):
        sent_docs.append((chat_id, filename, data, caption))
        return True

    set_last_run(8)
    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=fake_send))
    assert ok is True, ok
    assert len(sent_docs) == 1, len(sent_docs)
    chat_id, fname, data, caption = sent_docs[0]
    assert chat_id == 111, chat_id
    assert fname.startswith("nexora-auto-backup-"), fname
    assert fname.endswith(".json"), fname
    payload = json.loads(data.decode("utf-8"))
    assert payload["format"] == "nexora-backup", payload["format"]
    assert len(payload["tables"]) == 45, len(payload["tables"])
    assert "app_settings" in payload["tables"], list(payload["tables"])
    assert "auto_backup_enabled" in [
        r["key"] for r in payload["tables"]["app_settings"]], \
        payload["tables"]["app_settings"]
    assert "auto_backup_send" in audit_actions(), audit_actions()
    last_run = get_setting("auto_backup_last_run")
    assert last_run, last_run
    assert datetime.utcnow() - datetime.fromisoformat(last_run) \
        < timedelta(minutes=5), last_run
    r = c.get("/admin/auto-backup", headers=ALICE)
    assert r.json()["last_auto_backup_at"], r.json()
    # A second immediate run is not due — nothing more is sent.
    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=fake_send))
    assert ok is False, ok
    assert len(sent_docs) == 1, len(sent_docs)
    print("due run sends full backup to owner OK")

    # 5. A failed send logs, leaves last_run alone, retries fine.
    set_last_run(8)
    before = get_setting("auto_backup_last_run")

    async def failing_send(chat_id, filename, data, caption=""):
        return False

    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=failing_send))
    assert ok is False, ok
    assert len(sent_docs) == 1, len(sent_docs)
    assert get_setting("auto_backup_last_run") == before, \
        get_setting("auto_backup_last_run")
    assert "server_error" in security_kinds(), security_kinds()
    assert "auto_backup_failed" in audit_actions(), audit_actions()

    async def raising_send(chat_id, filename, data, caption=""):
        raise RuntimeError("telegram down")

    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=raising_send))
    assert ok is False, ok
    assert get_setting("auto_backup_last_run") == before
    # And the next check retries fine.
    ok = asyncio.run(main_mod._maybe_auto_backup(send_fn=fake_send))
    assert ok is True, ok
    assert len(sent_docs) == 2, len(sent_docs)
    assert get_setting("auto_backup_last_run") != before
    print("failed send logs + retries OK")

    # 6. The auto run did NOT consume the manual backup 10/h
    # budget: 10 manual downloads still succeed, the 11th 429s.
    for i in range(10):
        r = c.get("/admin/backup", headers=ALICE)
        assert r.status_code == 200, (i, r.status_code, r.text)
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 429, r.status_code
    print("manual backup budget untouched by auto-backup OK")

    # 7. Backup-status reports the last auto-backup.
    r = c.get("/admin/backup-status", headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["last_auto_backup_at"], r.json()
    print("backup-status last_auto_backup_at OK")

    # 8. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=170") == 10, html.count("?v=170")
    assert "?v=14" + "0" not in html
    js = open("webapp/app.js").read()
    for m in ("loadAutoBackup", "auto-backup-toggle", "auto-backup-line",
              "/admin/auto-backup", "Auto-backup"):
        assert m in js, m
    for m in ("auto-backup-toggle", "auto-backup-line",
              "Weekly auto-backup", "auto-backup-row"):
        assert m in html, m
    main_src = open("app/main.py").read()
    for m in ("_auto_backup_loop", "_maybe_auto_backup",
              "_auto_backup_due", "_auto_backup_enabled",
              "_auto_backup_last_run", "_auto_backup_next_due",
              "auto_backup_send", "auto_backup_failed",
              "auto_backup_enabled", "auto_backup_last_run",
              "_AUTO_BACKUP_INTERVAL_S", "_AUTO_BACKUP_PERIOD",
              "admin_auto_backup_status", "admin_auto_backup_set"):
        assert m in main_src, m
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
    print("client markers + ?v=170 OK")

print("ALL PHASE 141 CHECKS PASSED")
