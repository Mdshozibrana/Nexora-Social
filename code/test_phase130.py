"""Phase-130 tests: System Health card in the Admin Panel.

The Admin Panel had no in-app view of the platform's health — no
live version, commit, uptime, database size, row counts or recent
server errors. A failed deploy was only visible in the Render
dashboard. New admin-only GET /admin/health returns version (first
?v=NN in the deployed webapp/index.html on disk), commit (short
SHA from RENDER_GIT_COMMIT, else null), uptime_seconds (from a
module-level _STARTED_AT), db_size_bytes (pg_database_size on
Postgres, sqlite file size locally), row counts for nine key
tables, errors_24h + the last 5 server_error events (reusing the
Phase 128 security_events table). Client: "System Health" section,
14th cp-nav button right after Security Log, with cards + a
row-count table + recent errors + Refresh. No new table, no
_migrate change — backup stays at 35 tables.
"""

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase130.db"
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
from app.db import SessionLocal
from app import models

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


ADMIN = 999
HA = H(ADMIN, "Admin")
HB = H(882, "Mona")

AARON, MONA, ZED, KIM = 881, 882, 883, 884
NOW = datetime.utcnow()

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(BASE, "webapp", "index.html")).read()
JS = open(os.path.join(BASE, "webapp", "app.js")).read()
SRC = open(os.path.join(BASE, "app", "main.py")).read()


def seed():
    db = SessionLocal()
    db.add(models.User(telegram_id=AARON, first_name="Aaron",
                       username="aaron"))
    db.add(models.User(telegram_id=MONA, first_name="Mona",
                       username="mona"))
    db.add(models.User(telegram_id=ZED, first_name="Zed",
                       username="zed"))
    db.add(models.Post(user_id=AARON, type="text", caption="post 0"))
    db.add(models.Post(user_id=AARON, type="text", caption="post 1"))
    db.add(models.Post(user_id=MONA, type="text", caption="hello"))
    db.add(models.Design(image_file_id="f1", prompt="a design"))
    db.add(models.Design(image_file_id="f2", prompt="another"))
    # Posts get ids 1, 2, 3 in insertion order on a fresh DB.
    db.add(models.Comment(post_id=1, user_id=MONA, text="nice"))
    db.add(models.Like(post_id=1, user_id=MONA))
    db.add(models.PointsLedger(user_id=AARON, amount=50, reason="bonus"))
    db.add(models.Message(sender_id=AARON, recipient_id=MONA, text="hi"))
    # Errors: 1 recent server_error, 1 old (>24h) server_error,
    # 1 recent rate_limit (must NOT count as an error).
    # Inserted oldest first, so ids ascend with recency and the
    # newest-first query returns "boom recent" before "boom old".
    db.add(models.SecurityEvent(kind="server_error", actor_id=AARON,
                                detail="boom old",
                                created_at=NOW - timedelta(days=2)))
    db.add(models.SecurityEvent(kind="server_error", actor_id=AARON,
                                detail="boom recent",
                                created_at=NOW - timedelta(hours=1)))
    db.add(models.SecurityEvent(kind="rate_limit", actor_id=MONA,
                                detail="too fast",
                                created_at=NOW - timedelta(minutes=5)))
    db.commit()
    db.close()


def health(c):
    r = c.get("/admin/health", headers=HA)
    assert r.status_code == 200, r.text
    return r.json()


def test_source_guards():
    # Phase 126 lesson: no integer default on a boolean column in
    # raw migration SQL (Postgres rejects it, SQLite accepts it).
    assert "BOOLEAN DEFAULT 0" not in SRC, "boolean DEFAULT 0 present"
    assert "_STARTED_AT" in SRC
    assert "pg_database_size" in SRC
    assert "RENDER_GIT_COMMIT" in SRC
    assert "/admin/health" in SRC
    assert "_HEALTH_TABLES" in SRC
    print("source guards OK (no BOOLEAN DEFAULT 0, health endpoint present)")


def test_client_markers():
    assert HTML.count("?v=171") == 10, HTML.count("?v=171")
    assert "?v=129" not in HTML
    assert "app.js?v=171" in HTML and "style.css?v=171" in HTML
    for marker in ("loadHealth", "fmtUptime", "fmtBytes",
                   "/admin/health", "loadHealth()"):
        assert marker in JS, marker
    for marker in ("cp-sec-health", "admin-health", "health-refresh",
                   "health-checked", "System Health"):
        assert marker in HTML, marker
    assert HTML.count('data-target="cp-sec-') == 15, \
        HTML.count('data-target="cp-sec-')
    for marker in ("topScroller", "pollBlock", "loadDrafts",
                   "renderPh", "goFeedTo", "loadTrending",
                   "loadPayoutBox", "loadPayoutList", "loadPayouts",
                   "decidePayout", "markPayoutPaid", "loadSecurityLog",
                   "loadAdminBrowse", "adminBrowse"):
        assert marker in JS, marker
    print("client markers OK (?v=171, health UI, 123-129 intact)")


def test_health_values(c):
    h = health(c)
    # Version: the first ?v=NN in the deployed index.html on disk.
    import re as _re
    m = _re.search(r"\?v=(\d+)", HTML)
    assert m and h["version"] == int(m.group(1)) == 171, h["version"]
    # Commit: no RENDER_GIT_COMMIT in the test env -> null; if one
    # ever appears it must be a 7-char hex short SHA.
    commit = h["commit"]
    assert commit is None or (
        isinstance(commit, str) and len(commit) == 7
        and all(ch in "0123456789abcdef" for ch in commit)), commit
    assert isinstance(h["uptime_seconds"], int)
    assert h["uptime_seconds"] >= 0, h["uptime_seconds"]
    # SQLite fallback: the test DB file on disk, positive size.
    assert isinstance(h["db_size_bytes"], int)
    assert h["db_size_bytes"] > 0, h["db_size_bytes"]
    # Row counts. The warm-up /admin/health call (HA) provisions the
    # admin (999) + the official account (1) + its welcome post, and
    # the welcome post earns +10 points — hence users 5 (not 3),
    # posts 4 (not 3) and points_ledger 2 (not 1).
    assert h["tables"] == {
        "users": 5, "posts": 4, "designs": 2, "comments": 1,
        "likes": 1, "points_ledger": 2, "messages": 1,
        "security_events": 3, "payout_requests": 0,
    }, h["tables"]
    # Only the recent server_error counts; the old one and the
    # rate_limit event do not.
    assert h["errors_24h"] == 1, h["errors_24h"]
    recent = h["recent_errors"]
    assert len(recent) == 2, recent
    assert recent[0]["detail"] == "boom recent"
    assert recent[1]["detail"] == "boom old"
    assert recent[0]["id"] > recent[1]["id"], recent
    print("health values OK (version/uptime/db size/counts/errors)")


def test_recent_errors_cap(c):
    db = SessionLocal()
    for i in range(6):
        db.add(models.SecurityEvent(kind="server_error", actor_id=AARON,
                                    detail=f"cap {i}",
                                    created_at=NOW - timedelta(minutes=i)))
    db.commit()
    db.close()
    h = health(c)
    assert h["errors_24h"] == 7, h["errors_24h"]
    recent = h["recent_errors"]
    assert len(recent) == 5, recent
    ids = [e["id"] for e in recent]
    assert ids == sorted(ids, reverse=True), ids
    assert [e["detail"] for e in recent] == [
        "cap 5", "cap 4", "cap 3", "cap 2", "cap 1"], recent
    print("recent_errors cap OK (at most 5, newest first)")


def test_auth(c):
    r = c.get("/admin/health", headers=HB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/health", headers={})
    assert r.status_code == 401, r.status_code
    print("auth 403/401 OK")


if __name__ == "__main__":
    seed()
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200, r.text
        # Warm-up: settle lazy user creation (admin + official)
        # before counting rows for the table assertions.
        health(c)
        test_source_guards()
        test_client_markers()
        test_health_values(c)
        test_recent_errors_cap(c)
        test_auth(c)
    print("test_phase130: ALL OK")
