"""Phase-132 tests: backup reminder in the Admin Panel.

Covers: GET /admin/backup-status returns all-nulls on a fresh DB;
after an admin backup download last_backup_at is set with kind
"download" and last_restore_at stays null; after a backup send
(mocked) kind becomes "send"; after a restore last_restore_at is
set and the last backup (from the restored audit rows) survives;
non-admin 403, unauthenticated 401; backup still carries 39 tables;
?v=136 x5, no ?v=136; backup-reminder client markers + Phase 123-131
markers intact.
"""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase132.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.notify as notify_mod

SEND_DOC_CALLS = []


async def fake_send_document(chat_id, fname, data, caption=None):
    SEND_DOC_CALLS.append((chat_id, fname))
    return True


notify_mod.send_document = fake_send_document

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


def status(c, headers=ADMIN):
    r = c.get("/admin/backup-status", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


with TestClient(app) as c:
    for h in (ADMIN, BOB):
        assert c.post("/auth", json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Fresh DB: nothing backed up or restored yet.
    s = status(c)
    assert s == {"last_backup_at": None, "last_backup_kind": None,
                 "last_restore_at": None}, s
    print("backup-status all-nulls on fresh DB OK")

    # 2. Auth boundaries.
    r = c.get("/admin/backup-status", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/backup-status")
    assert r.status_code == 401, r.status_code
    print("backup-status auth OK")

    # 3. Download: kind "download", restore still null.
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    s = status(c)
    assert s["last_backup_at"] is not None, s
    assert s["last_backup_kind"] == "download", s
    assert s["last_restore_at"] is None, s
    print("backup-status after download OK")

    # 4. Send to Telegram (mocked): kind becomes "send".
    r = c.post("/admin/backup/send", headers=ADMIN)
    assert r.status_code == 200 and r.json() == {"sent": True}, r.text
    assert len(SEND_DOC_CALLS) == 1, SEND_DOC_CALLS
    s = status(c)
    assert s["last_backup_kind"] == "send", s
    assert s["last_backup_at"] is not None, s
    assert s["last_restore_at"] is None, s
    print("backup-status after send OK")

    # 5. Restore: last_restore_at is set; the last backup (audit rows
    #    carried inside the backup payload) survives the wipe.
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    b = r.json()
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE", "backup": b})
    assert r.status_code == 200, r.text
    s = status(c)
    assert s["last_restore_at"] is not None, s
    assert s["last_backup_at"] is not None, s
    assert s["last_backup_kind"] == "send", s
    with SessionLocal() as db:
        assert db.query(models.AdminAuditLog).filter_by(
            action="backup_restore").count() == 1
    print("backup-status after restore OK")

    # 6. Backup still carries 39 tables, no migration change.
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.status_code
    assert len(r.json()["tables"]) == 39, len(r.json()["tables"])
    print("backup: 39 tables OK")

    # 7. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=136") == 5, html.count("?v=136")
    assert "?v=131" not in html
    assert 'id="backup-reminder"' in html
    assert 'id="backup-warn"' in html
    js = open("webapp/app.js").read()
    for m in ("loadBackupStatus", "/admin/backup-status",
              "Last backup: ", "Last restore: ",
              "No backup taken yet", "No backup in "):
        assert m in js, m
    css = open("webapp/style.css").read()
    assert ".backup-warn" in css, css
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "BC_TARGET_LABELS"):
        assert m in js, m
    print("client markers + ?v=136 OK")

print("PHASE-132 TESTS PASSED")
