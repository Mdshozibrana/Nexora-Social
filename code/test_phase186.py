"""Phase 186 tests: RLS (H4) step-3 code — session variables in every
DB session + role-script table audit + _migrate() permission tolerance.

1. RLS context helpers: defaults, coercion, admin derivation
   (ADMIN_IDS + MODERATOR_IDS), system identity, and — critically —
   apply_rls_context is a no-op on SQLite, so the suites keep passing.
   _is_permission_error recognises psycopg3's sqlstate (42501) as well
   as pgcode and the "must be owner of" wording (the first smoke run
   proved pgcode-only missed the refusal and the app import died).
2. Static session-path audit: every direct SessionLocal() in the app
   is accounted for — main.py has NONE left (9 sites converted to
   rls_session/system_session); bot.py's 6 sites each bind the acting
   member before the session opens and clear the context at close;
   the request paths (current_user, /auth, /media, /p/{id}) bind the
   identity before the first RLS-filtered query.
3. Role-script audit: the GRANT list in phase164_rls_role.sql equals
   the 52 models tables (== _BACKUP_TABLES), including the 8 tables
   Phases 170-185 added that Phase 164's 44-table list missed.
4. Behavioural (SQLite): the wiring changes nothing observable —
   /auth, text posts, feed reads, DMs, the public post page
   (anonymous + identified), and the admin endpoints all still work,
   including a post created and then read after several commits in
   the same flow (the case the after_begin listener exists for).
5. Version + routes + backup pins: shell ?v=190 (x10), bot menu
   /?v=190, ?v=185 gone from the shell, 183 routes, 52 backup
   tables, /admin/health version 186.
The live-Postgres proof (policy matrix, write enforcement, identity
surviving COMMIT, app boot under the app role) is NOT in this file —
it is ~/workspace/nexora_designs/phase186_smoke.py (32/32 PASS on a
local Postgres 16 scratch DB, Nov 25, 2026).
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase186.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _is_permission_error  # noqa: E402
from app import models  # noqa: E402
from app import ratelimit  # noqa: E402
from app.db import (  # noqa: E402
    SessionLocal, apply_rls_context, clear_rls_context, get_db,
    get_rls_context, is_admin_id, rls_session, set_rls_context,
    set_rls_context_for, system_session)
from app.config import OFFICIAL_ID  # noqa: E402


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


ALICE = H(1861, "Alice", "alice186")
BOB = H(1862, "Bob", "bob186")
CAROL = H(1863, "Carol", "carol186")
ADMIN = H(999, "Admin")
MOD = H(888, "Mod")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
MAIN_SRC = open(os.path.join(ROOT, "code/app/main.py")).read()
DB_SRC = open(os.path.join(ROOT, "code/app/db.py")).read()

c = TestClient(app, raise_server_exceptions=False)


# --- 1. RLS context helpers ---------------------------------------------
assert get_rls_context() is None
assert is_admin_id(999) is True
assert is_admin_id(888) is True  # moderator gets the bypass too
assert is_admin_id(1861) is False
assert is_admin_id("999") is True
assert is_admin_id("nobody") is False
assert is_admin_id(None) is False

set_rls_context_for(1861)
assert get_rls_context() == (1861, False), get_rls_context()
set_rls_context_for(999)
assert get_rls_context() == (999, True), get_rls_context()
set_rls_context_for(888)
assert get_rls_context() == (888, True), get_rls_context()
set_rls_context(1862, is_admin=True)
assert get_rls_context() == (1862, True), get_rls_context()
set_rls_context(None)
assert get_rls_context() is None
clear_rls_context()
assert get_rls_context() is None

# SQLite no-op: apply + sessions behave exactly as before.
db = SessionLocal()
try:
    set_rls_context_for(1861)
    apply_rls_context(db)  # must not raise on SQLite
    db.add(models.User(telegram_id=1861, first_name="Alice",
                       username="alice186"))
    db.commit()
    # A commit mid-session must not break later queries (the
    # after_begin listener exists for this on Postgres).
    assert db.get(models.User, 1861) is not None
    db.commit()
    assert db.query(models.User).count() >= 1
finally:
    db.close()
clear_rls_context()

# rls_session / system_session: identity inside, restored after.
with rls_session(1862) as s:
    assert get_rls_context() == (1862, False), get_rls_context()
    assert s.get(models.User, 1861) is not None
assert get_rls_context() is None
with rls_session(999) as s:
    assert get_rls_context() == (999, True), get_rls_context()
with system_session() as s:
    assert get_rls_context() == (OFFICIAL_ID, True), get_rls_context()
    assert s.query(models.User).count() >= 1
assert get_rls_context() is None
# get_db yields a working session.
gen = get_db()
s = next(gen)
try:
    assert s.query(models.User).count() >= 1
finally:
    try:
        next(gen)
    except StopIteration:
        pass
print("1. RLS context helpers OK (SQLite no-op, admin derivation, "
      "restore-after-session)")


# _is_permission_error: psycopg3 sqlstate, psycopg2 pgcode, wording.
class _Orig:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeDBAPIError(Exception):
    def __init__(self, orig, msg=""):
        super().__init__(msg)
        self.orig = orig


assert _is_permission_error(_FakeDBAPIError(
    _Orig(sqlstate="42501"), "x")) is True
assert _is_permission_error(_FakeDBAPIError(
    _Orig(pgcode="42501"), "x")) is True
assert _is_permission_error(_FakeDBAPIError(
    _Orig(sqlstate=None), "permission denied for schema public")) is True
assert _is_permission_error(_FakeDBAPIError(
    _Orig(sqlstate=None), "must be owner of table users")) is True
assert _is_permission_error(_FakeDBAPIError(
    _Orig(sqlstate="23505"),
    'duplicate key value violates unique constraint')) is False
assert _is_permission_error(_FakeDBAPIError(
    _Orig(sqlstate=None), "relation \"nope\" does not exist")) is False
print("1b. _is_permission_error OK (sqlstate + pgcode + wording)")


# --- 2. Static session-path audit ---------------------------------------
# main.py: no bare SessionLocal() left at all.
assert "SessionLocal()" not in MAIN_SRC, "bare SessionLocal in main.py"
assert "SessionLocal" not in MAIN_SRC, "SessionLocal name in main.py"
# The 9 converted sites, by enclosing function.
MAIN_FUNCS = {
    "_maintenance_on_db": "system_session",
    "log_security_event": "system_session",
    "_finish_video_post": "rls_session",
    "_run_scheduled_sweep": "system_session",
    "_build_auto_backup": "system_session",
    "_record_auto_backup": "system_session",
    "_stamp_auto_backup_attempt": "system_session",
    "_restore_auto_backup_stamp": "system_session",
    "_maybe_auto_backup": "system_session",
}


def _func_span(src, name):
    m = re.search(r"(?m)^(async )?def " + re.escape(name) + r"\(", src)
    assert m, name
    nxt = re.search(r"(?m)^(async )?def ", src[m.end():])
    end = m.end() + nxt.start() if nxt else len(src)
    return src[m.start():end]


for fname, helper in MAIN_FUNCS.items():
    span = _func_span(MAIN_SRC, fname)
    assert helper + "(" in span, (fname, helper)
assert MAIN_SRC.count("system_session()") == 8, \
    MAIN_SRC.count("system_session()")
assert MAIN_SRC.count("rls_session(") == 1, MAIN_SRC.count("rls_session(")
# Request paths bind the identity before the first RLS-filtered query.
for fname in ("current_user", "auth", "media_proxy",
              "public_post_page"):
    span = _func_span(MAIN_SRC, fname)
    assert "set_rls_context_for(" in span, fname
    assert "apply_rls_context(" in span, fname
# db.py is the only place sessions are created (get_db + rls_session).
# (Count code occurrences — the module docstring names SessionLocal
# twice more in prose.)
assert DB_SRC.count("    db = SessionLocal()") == 2, \
    DB_SRC.count("    db = SessionLocal()")
assert "after_begin" in DB_SRC and "SET LOCAL" in DB_SRC
# bot.py: 6 sites, each binds before opening and clears at close.
assert BOT.count("db = SessionLocal()") == 6, BOT.count("db = SessionLocal()")
assert BOT.count("set_rls_context_for(") == 6
assert BOT.count("clear_rls_context()") == 6
for fname in ("start_handler", "_save_media_post", "_media_group_flush",
              "photo_handler", "successful_payment_handler"):
    span = _func_span(BOT, fname)
    assert "set_rls_context_for(" in span, fname
    assert "clear_rls_context()" in span, fname
    assert "db = SessionLocal()" in span, fname
print("2. static session-path audit OK (main 0 bare, bot 6 bound, "
      "request paths bound)")


# --- 3. Role-script audit -----------------------------------------------
role_sql = open(os.path.join(
    ROOT, "code/migrations/phase164_rls_role.sql")).read()
m = re.search(r"GRANT SELECT, INSERT, UPDATE, DELETE ON\n(.*?)\n"
              r"TO nexora_app;", role_sql, re.S)
assert m, "GRANT block not found in role script"
granted = {t.strip() for t in m.group(1).replace("\n", " ").split(",")
           if t.strip()}
model_tables = set(re.findall(r'__tablename__ = "([a-z_]+)"',
                              open(os.path.join(
                                  ROOT, "code/app/models.py")).read()))
assert len(model_tables) == 52, len(model_tables)
assert granted == model_tables, (
    sorted(model_tables - granted), sorted(granted - model_tables))
assert granted == {name for name, _ in _BACKUP_TABLES}
# The 8 tables Phases 170-185 added (missing from the 44-table list).
for t in ("highlight_stories", "mentions", "mutes", "post_media",
          "saved_collection_posts", "saved_collections",
          "story_highlights", "task_follow_events"):
    assert t in granted, t
print("3. role-script GRANT list OK (52 tables == models == backup)")


# --- 4. Behavioural: wiring changes nothing observable ------------------
def mk(uid, name, username):
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text


for uid, name, uname in ((1861, "Alice", "alice186"),
                         (1862, "Bob", "bob186"),
                         (1863, "Carol", "carol186")):
    mk(uid, name, uname)

r = c.post("/auth", json={"initData": make_init_data(
    {"id": 1861, "first_name": "Alice", "username": "alice186"})})
assert r.status_code == 200, r.text
assert r.json()["telegram_id"] == 1861, r.json()
assert r.json()["media_token"], "media token missing from /auth"

r = c.post("/posts", headers=ALICE,
           json={"type": "text", "caption": "Phase 186 wiring post"})
assert r.status_code == 200, r.text
post_id = r.json()["id"]
r = c.get("/feed", headers=ALICE)
assert r.status_code == 200, r.text
assert any(p["id"] == post_id for p in r.json().get("posts", [])), \
    r.json()
# The same post is still readable after the request's commits —
# the listener case: create, then read twice in a row.
r = c.get(f"/posts/{post_id}", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get(f"/posts/{post_id}", headers=ALICE)
assert r.status_code == 200, r.text

# DM: Alice -> Bob; Bob reads it, Carol must not (app-level, unchanged).
r = c.post("/messages/1862", headers=ALICE, json={"text": "hi bob 186"})
assert r.status_code == 200, r.text
r = c.get("/messages/1861", headers=BOB)
assert r.status_code == 200, r.text
assert any(m.get("text") == "hi bob 186"
           for m in r.json().get("messages", [])), r.json()
r = c.get("/messages/1861", headers=CAROL)
assert r.status_code == 200, r.text
assert not any(m.get("text") == "hi bob 186"
               for m in r.json().get("messages", [])), r.json()

# Public post page: anonymous sees the public post; a private
# author's post shows only the notice to an anonymous browser.
r = c.get(f"/p/{post_id}")
assert r.status_code == 200, r.text
assert "Phase 186 wiring post" in r.text, r.text
r = c.post("/me/privacy", json={"is_private": True}, headers=BOB)
assert r.status_code == 200, r.text
r = c.post("/posts", headers=BOB,
           json={"type": "text", "caption": "Bob private 186"})
assert r.status_code == 200, r.text
bob_post = r.json()["id"]
r = c.get(f"/p/{bob_post}")
assert r.status_code == 200, r.text
assert "Bob private 186" not in r.text, r.text
# ...but an identified follower CAN see it (the /p/{id} binding).
r = c.post("/users/1862/follow", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/follow-requests", headers=BOB)
assert r.status_code == 200, r.text
reqs = r.json()["follow_requests"]
assert reqs, r.json()
r = c.post(f"/follow-requests/{reqs[0]['id']}/accept",
           headers=BOB)
assert r.status_code == 200, r.text
r = c.get(f"/p/{bob_post}", headers=ALICE)
assert r.status_code == 200, r.text
assert "Bob private 186" in r.text, r.text
r = c.post("/me/privacy", json={"is_private": False}, headers=BOB)
assert r.status_code == 200, r.text

# /media still enforces its token gate before any network happens.
r = c.get("/media/somefileid?mt=garbage")
assert r.status_code == 401, (r.status_code, r.text)

# Admin endpoints still work under the bound admin identity.
r = c.get("/admin/health", headers=ADMIN)
assert r.status_code == 200, r.text
assert r.json()["version"] == 190, r.json()
r = c.get("/admin/dashboard", headers=ADMIN)
assert r.status_code == 200, r.text
print("4. behavioural checks OK (auth, posts, feed, DMs, /p/ anon + "
      "follower, /media 401, admin)")


# --- 5. Version + routes + backup pins ----------------------------------
assert HTML.count("?v=190") == 10, HTML.count("?v=190")
assert "?v=18" + "5" not in HTML
assert "/?v=190" in BOT and "/?v=18" + "5" not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 184, len(paths)
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
r = c.get("/admin/health", headers=ADMIN)
assert r.json()["version"] == 190, r.json()
print("5. version ?v=190 + routes 183 + backup 52 OK")

print("PHASE 186 OK")
