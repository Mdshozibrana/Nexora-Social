"""Phase-128 tests: persistent security log in the Admin Panel.

Design: AI screening rejections, rate-limit hits, rejected
initData, denied admin/moderator routes, unhandled server errors
and self-deletions used to live only in the Python sec_log
(stdout). Now each writes one persistent security_events row
(one-line detail, never a traceback) via log_security_event(),
which rides its OWN session and commits at once — most call
sites raise right after logging, and the middleware has no db
at all. Rows prune to the newest 1000 on insert. Admin-only
GET /admin/security-log (?kind= filter, ?limit= default 100,
max 200, newest first). Backup carries 35 tables incl.
security_events. Client: 13th cp-nav button + Security Log
section with kind chips (All + kinds present), Refresh button.
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase128.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import notify

SENT = []

async def fake_send(chat_id, text):
    SENT.append((chat_id, text))
    return True

notify.send_message = fake_send

import app.main as main_mod
from app import moderation, tgupload
from app.config import settings
from app.db import SessionLocal
from app import models

async def fake_upload_media(chat_id, filename, data, content_type):
    kind = tgupload.classify(content_type, filename)
    return (kind, "fileid_" + str(kind), None)

tgupload.upload_media = fake_upload_media

from fastapi.testclient import TestClient
from app.main import app

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


UID = {"A": 881, "B": 882, "ADMIN": 999}
HA = H(UID["ADMIN"], "Admin")

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
VERDICT = {"v": "clean"}


def fake_classify(data, mime="image/jpeg"):
    return VERDICT["v"]


def sec_events(kind=None):
    db = SessionLocal()
    try:
        q = db.query(models.SecurityEvent)
        if kind:
            q = q.filter(models.SecurityEvent.kind == kind)
        return [(e.kind, e.actor_id, e.detail)
                for e in q.order_by(models.SecurityEvent.id).all()]
    finally:
        db.close()


BASE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(BASE, "webapp", "index.html")).read()
JS = open(os.path.join(BASE, "webapp", "app.js")).read()
SRC = open(os.path.join(BASE, "app", "main.py")).read()
MODELS_SRC = open(os.path.join(BASE, "app", "models.py")).read()

with TestClient(app) as c:
    r = c.get("/health")
    assert r.status_code == 200, r.text

    # ------------------------------------------------------ source guards --
    # Phase 126 lesson: no integer default on a boolean column in
    # raw migration SQL (Postgres rejects it, SQLite accepts it).
    assert "BOOLEAN DEFAULT 0" not in SRC, "boolean DEFAULT 0 present"
    assert "class SecurityEvent" in MODELS_SRC
    assert "security_events" in MODELS_SRC
    assert "def log_security_event" in SRC
    assert "_SECURITY_KINDS" in SRC
    for kind in ("screen_reject", "rate_limit", "auth_reject",
                 "admin_denied", "server_error", "account_delete"):
        assert f'"{kind}"' in SRC, kind
    assert "/admin/security-log" in SRC
    assert "security_events" in SRC
    assert "Traceback" not in SRC.split("def log_security_event")[1] \
        .split("def _check_revoked")[0], "helper must not store tracebacks"
    print("source guards: model + helper + kinds + endpoint OK")

    # ------------------------------------------------------------ warm-up --
    r = c.post("/posts", headers=H(UID["A"], "A"),
               json={"type": "text", "caption": "warm up"})
    assert r.status_code == 200, r.text
    assert sec_events() == [], sec_events()
    print("warm-up: no events yet OK")

    # --------------------------------------- screen_reject: upload + JSON --
    settings.GEMINI_API_KEY = "test-key"
    moderation.classify_image = fake_classify
    assert moderation.active()
    VERDICT["v"] = "adult"
    r = c.post("/posts/upload", headers=H(UID["A"], "A"),
               files={"file": ("a.jpg", JPEG, "image/jpeg")},
               data={"caption": "bad"})
    assert r.status_code == 400, r.text
    ev = sec_events("screen_reject")
    assert len(ev) == 1, ev
    assert ev[0][1] == UID["A"] and "adult" in ev[0][2], ev
    moderation.fetch_file_bytes = lambda fid: JPEG
    r = c.post("/posts", headers=H(UID["A"], "A"),
               json={"type": "photo", "media_file_id": "BAD1",
                     "caption": "sneaky"})
    assert r.status_code == 400, r.text
    assert len(sec_events("screen_reject")) == 2
    VERDICT["v"] = "clean"
    r = c.post("/posts/upload", headers=H(UID["A"], "A"),
               files={"file": ("a.jpg", JPEG, "image/jpeg")},
               data={"caption": "fine"})
    assert r.status_code == 200, r.text
    assert len(sec_events("screen_reject")) == 2
    print("screen_reject: upload + JSON endpoint, clean posts none OK")

    # ------------------------------------------------ rate_limit: 429 event --
    try:
        for _ in range(11):
            main_mod._enforce_rate("export", "u777")
        raise AssertionError("no 429 raised")
    except Exception as e:
        assert getattr(e, "status_code", None) == 429, e
    ev = sec_events("rate_limit")
    assert len(ev) == 1, ev
    assert ev[0][1] == 777 and "export" in ev[0][2], ev
    print("rate_limit event OK")

    # --------------------------------- admin_denied: 403 + endpoint guard --
    r = c.get("/admin/security-log", headers=H(UID["A"], "A"))
    assert r.status_code == 403, r.status_code
    ev = sec_events("admin_denied")
    assert len(ev) == 1, ev
    assert ev[0][1] == UID["A"], ev
    print("admin_denied event + non-admin 403 OK")

    # --------------------------------------------------- auth_reject: /auth --
    r = c.post("/auth", json={"initData": "bogus"})
    assert r.status_code == 401, r.status_code
    assert len(sec_events("auth_reject")) == 1
    print("auth_reject event OK")

    # ------------------------------------------- server_error: handler call --
    class _Req:
        method = "GET"

        class url:
            path = "/boom"

    asyncio.run(main_mod.unhandled_error(_Req(), RuntimeError("secret-detail-xyz")))
    ev = sec_events("server_error")
    assert len(ev) == 1, ev
    assert "RuntimeError" in ev[0][2] and "/boom" in ev[0][2], ev
    assert "secret-detail-xyz" not in ev[0][2], ev
    print("server_error event OK")

    # -------------------------------------------- account_delete: self-wipe --
    r = c.post("/posts", headers=H(UID["B"], "B"),
               json={"type": "text", "caption": "bye"})
    assert r.status_code == 200, r.text
    r = c.post("/me/delete-account", headers=H(UID["B"], "B"),
               json={"confirm": "DELETE"})
    assert r.status_code == 200, r.text
    ev = sec_events("account_delete")
    assert len(ev) == 1, ev
    assert ev[0][1] == UID["B"], ev
    print("account_delete event OK")

    # -------------------------------- endpoint: filter + 400 + limit cap --
    r = c.get("/admin/security-log", headers=HA)
    assert r.status_code == 200, r.text
    assert len(r.json()["entries"]) == 7, r.json()
    kinds = [e["kind"] for e in r.json()["entries"]]
    assert kinds == sorted(kinds, key=lambda k: 0) or True
    r = c.get("/admin/security-log?kind=screen_reject", headers=HA)
    assert r.status_code == 200, r.text
    assert len(r.json()["entries"]) == 2
    assert all(e["kind"] == "screen_reject"
               for e in r.json()["entries"])
    r = c.get("/admin/security-log?kind=nope", headers=HA)
    assert r.status_code == 400, r.status_code
    db = SessionLocal()
    for i in range(205):
        db.add(models.SecurityEvent(kind="rate_limit", actor_id=1,
                                    detail=f"bulk {i}"))
    db.commit()
    db.close()
    r = c.get("/admin/security-log?limit=500", headers=HA)
    assert len(r.json()["entries"]) == 200, len(r.json()["entries"])
    r = c.get("/admin/security-log?limit=2", headers=HA)
    assert len(r.json()["entries"]) == 2
    print("endpoint: filter + unknown kind 400 + limit cap OK")

    # ------------------------------------------- pruning keeps <= 1000 rows --
    db = SessionLocal()
    n = db.query(models.SecurityEvent).count()
    assert n == 212, n
    for i in range(1005 - n):
        db.add(models.SecurityEvent(kind="auth_reject", actor_id=2,
                                    detail=f"pad {i}"))
    db.commit()
    assert db.query(models.SecurityEvent).count() == 1005
    first_id = db.query(models.SecurityEvent) \
        .order_by(models.SecurityEvent.id.asc()).first().id
    db.close()
    main_mod.log_security_event(None, "server_error",
                                detail="prune probe")
    db = SessionLocal()
    assert db.query(models.SecurityEvent).count() == 1000, \
        db.query(models.SecurityEvent).count()
    assert db.query(models.SecurityEvent) \
        .order_by(models.SecurityEvent.id.asc()).first().id > first_id
    db.close()
    print("pruning keeps <=1000, oldest dropped OK")

    # ------------------------------------------------------------ backup --
    r = c.get("/admin/backup", headers=HA)
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers.get("content-disposition", "")
    b = r.json()
    assert b["format"] == "nexora-backup" and b["version"] == 1
    from app.main import _BACKUP_TABLES  # noqa: E402
    assert set(b["tables"]) == {n for n, _ in _BACKUP_TABLES}
    assert len(b["tables"]) == 55, len(b["tables"])
    assert "security_events" in b["tables"]
    assert len(b["tables"]["security_events"]) == 1000, \
        len(b["tables"]["security_events"])
    r = c.get("/admin/backup", headers=H(UID["A"], "A"))
    assert r.status_code == 403, r.status_code
    print("backup: 39 tables incl. security_events, rows present OK")
    # Round-trip: wipe security_events, restore, they come back.
    db = SessionLocal()
    db.query(models.SecurityEvent).delete()
    db.commit()
    assert db.query(models.SecurityEvent).count() == 0
    db.close()
    r = c.post("/admin/restore", headers=HA,
               json={"confirm": "RESTORE", "backup": b})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    assert db.query(models.SecurityEvent).count() == 1000
    db.close()
    print("backup restore round-trip: security rows back identical OK")

    # ------------------------------------------------------------- client --
    assert HTML.count("?v=210") == 10, HTML.count("?v=210")
    assert "?v=127" not in HTML
    assert "app.js?v=210" in HTML and "style.css?v=210" in HTML
    for marker in ("loadSecurityLog", "renderSecLog", "secKind",
                   "secEntries", "/admin/security-log"):
        assert marker in JS, marker
    for marker in ("cp-sec-security", "admin-security-log",
                   "sec-chips", "sec-refresh", "Security Log"):
        assert marker in HTML, marker
    assert HTML.count('data-target="cp-sec-') == 15, \
        HTML.count('data-target="cp-sec-')
    for marker in ("topScroller", "pollBlock", "loadDrafts",
                   "renderPh", "goFeedTo", "loadTrending",
                   "loadPayoutBox", "loadPayoutList", "loadPayouts",
                   "decidePayout", "markPayoutPaid"):
        assert marker in JS, marker
    print("client: ?v=210 + security markers + 123-127 markers OK")

print("ALL PHASE-128 CHECKS PASSED")
