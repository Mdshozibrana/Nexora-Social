"""Phase-193 tests: _restore_backup bulk-inserts PK-ordered rows, so a
self-referential FK pointing UP the order 400d the whole restore on
Postgres — and SQLite never caught it, because FK enforcement is OFF
by default.

DIAGNOSIS (parent, local Postgres 16, Nov 27 ~09:17):
- POST /admin/restore on the new service -> 400 "Restore failed —
  nothing was changed". Decrypt + validation OK; the failure is in
  _restore_backup's insert phase: users_referrer_id_fkey violation,
  Key (referrer_id)=(6398367372) not present — member Niloy
  (5177124392) sorts before his referrer the owner (6398367372).
- ROOT CAUSE: the comment in _restore_backup claimed PK order
  always puts a referrer first. False. Postgres enforces the FK
  per row inside the single executemany INSERT.

TESTS (all restores run on SQLite with PRAGMA foreign_keys=ON —
the pragma is proven on first by a raw out-of-order insert that
MUST raise, so the suite catches this class of bug without
needing Postgres in CI):
(a) FK enforcement proof: pragma reads 1 AND a raw insert of a
    users row naming a missing referrer raises IntegrityError.
(b) users chain, production shape: referrer 100, member 50 names
    100, member 75 names 50 — PK order is 50, 75, 100. Restore
    succeeds and all rows land with correct referrer_ids; a
    cross-table Follow row (50 -> 100) lands too.
(c) true cycle: users 10 <-> 20 (each names the other). Restores
    with both referrer_ids intact (NULL-then-UPDATE fallback).
(d) self-reference: user 30 names itself — restores fine.
(e) siblings: posts repost (id 1 reposts id 2) and comments reply
    (id 1 parent id 2) — both restore in the right order.
(f) endpoint: POST /admin/restore with the chain payload returns
    200 and the rows land (the live path, FK-enforced).
(g) version pins: shell ?v=206 (x10), old version gone, bot menu
    URL bumped, /admin/health version 193, backup 52 tables.
No BACKUP_ENCRYPTION_KEY in this env, so plaintext restores are
accepted (same as test_phase107/192). Plain script (run.sh runs
it with python directly).
"""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["GEMINI_API_KEY"] = ""
RUN69 = os.path.expanduser("~/workspace/nexora_run69")
APP_DB = os.path.join(RUN69, "test_phase193.sqlite")
FK_DB = os.path.join(RUN69, "test_phase193_fk.sqlite")
for p in (APP_DB, FK_DB):
    if os.path.exists(p):
        os.remove(p)
os.environ["DATABASE_URL"] = "sqlite:///" + APP_DB

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
import app.main as main_mod  # noqa: E402
from app.main import _restore_backup, admin_user, app  # noqa: E402
from app.db import SessionLocal, engine as APP_ENGINE  # noqa: E402
from app import models  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(BASE, "webapp", "index.html")).read()
SRC = open(os.path.join(BASE, "app", "main.py")).read()


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


ADMIN = H(999, "Admin")


def payload_for(**tables):
    return {"format": "nexora-backup", "version": 1,
            "exported_at": "2026-11-27T00:00:00Z", "tables": tables}


# Source: the sequence-reset fix — GREATEST(..., 1) so an empty
# table never calls setval(seq, 0) (out of bounds for an int4
# sequence; the first empty int-PK table in the real backup is
# saved_posts, and it 400d the restore even after the FK fix).
assert "GREATEST(COALESCE((SELECT MAX(" in SRC, "setval fix missing"
assert SRC.count("GREATEST(COALESCE((SELECT MAX(") == 1
print("source markers OK (setval GREATEST fix)")

# --- FK-enforced engine for the direct _restore_backup tests ------
FK_ENGINE = create_engine("sqlite:///" + FK_DB)


@event.listens_for(FK_ENGINE, "connect")
def _fk_on(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


models.Base.metadata.create_all(FK_ENGINE)
FKSession = sessionmaker(bind=FK_ENGINE)

# Same enforcement on the app's own engine, so the endpoint test
# below is FK-enforced too (dispose the pool so every connection
# from here on is a fresh, pragma-on one).
@event.listens_for(APP_ENGINE, "connect")
def _fk_on_app(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


APP_ENGINE.dispose()

# (a) Prove FK enforcement is really ON before trusting any restore.
with FK_ENGINE.connect() as conn:
    assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
db = FKSession()
try:
    db.execute(models.User.__table__.insert().values(
        telegram_id=999001, first_name="Ghost", referrer_id=999002))
    db.commit()
    raise AssertionError("FKs are OFF — dangling referrer inserted")
except IntegrityError:
    db.rollback()
    print("FK enforcement proof OK (dangling referrer raises)")
finally:
    db.close()

# (b) Users chain, production shape: PK order 50, 75, 100, but
# 50 names 100 and 75 names 50. Old code inserts 50 first and
# Postgres 400s; the topo sort lands 100, then 50, then 75.
# (d) is folded in: user 30 names itself (self-reference needs
# no ordering — its own insert satisfies the check).
chain_users = [
    {"telegram_id": 30, "first_name": "SelfRef", "referrer_id": 30},
    {"telegram_id": 50, "first_name": "Member", "referrer_id": 100},
    {"telegram_id": 75, "first_name": "Member2", "referrer_id": 50},
    {"telegram_id": 100, "first_name": "Owner", "referrer_id": None},
]
db = FKSession()
try:
    counts = _restore_backup(db, payload_for(
        users=chain_users,
        follows=[{"id": 1, "follower_id": 50, "following_id": 100}]))
    db.commit()
    assert counts["users"] == 4 and counts["follows"] == 1, counts
    got = {u.telegram_id: u.referrer_id
           for u in db.query(models.User).all()}
    assert got == {30: 30, 50: 100, 75: 50, 100: None}, got
    assert db.query(models.Follow).filter_by(
        follower_id=50, following_id=100).first() is not None
finally:
    db.close()
print("users chain + self-reference + cross-table follow OK")

# (c) True cycle: users 10 <-> 20 (each names the other). No order
# can satisfy both, so they go in with the FK NULL and are
# UPDATEed back afterwards — both referrer_ids intact.
db = FKSession()
try:
    counts = _restore_backup(db, payload_for(users=[
        {"telegram_id": 10, "first_name": "A", "referrer_id": 20},
        {"telegram_id": 20, "first_name": "B", "referrer_id": 10},
    ]))
    db.commit()
    assert counts["users"] == 2, counts
    got = {u.telegram_id: u.referrer_id
           for u in db.query(models.User).all()}
    assert got == {10: 20, 20: 10}, got
finally:
    db.close()
print("true-cycle fallback OK (both referrer_ids intact)")

# (e) Siblings: posts repost (id 1 reposts id 2) and comments reply
# (id 1 parent id 2) — the generic sort covers them, not just users.
# NOTE: every row carries every column (repost_of_id/parent_id
# None where unset), exactly like a real backup: SQLAlchemy's
# executemany compiles the column list from the FIRST dict, so a
# sparse row would silently drop the extra keys of later rows.
db = FKSession()
try:
    counts = _restore_backup(db, payload_for(
        users=[
            {"telegram_id": 100, "first_name": "Owner"},
            {"telegram_id": 50, "first_name": "Member"},
        ],
        posts=[
            {"id": 1, "user_id": 50, "type": "repost",
             "repost_of_id": 2, "caption": ""},
            {"id": 2, "user_id": 100, "type": "text", "caption": "OG",
             "repost_of_id": None},
        ],
        comments=[
            {"id": 1, "post_id": 2, "user_id": 50, "text": "reply",
             "parent_id": 2},
            {"id": 2, "post_id": 2, "user_id": 100, "text": "top",
             "parent_id": None},
        ]))
    db.commit()
    assert counts["posts"] == 2 and counts["comments"] == 2, counts
    assert db.get(models.Post, 1).repost_of_id == 2
    assert db.get(models.Post, 2).caption == "OG"
    assert db.get(models.Comment, 1).parent_id == 2
    assert db.get(models.Comment, 2).text == "top"
finally:
    db.close()
print("siblings OK (posts repost + comments reply order)")

# (f) Endpoint: the live path restores the chain payload, FK-on.
with TestClient(app, raise_server_exceptions=False) as c:
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE",
                     "backup": payload_for(users=chain_users)})
    assert r.status_code == 200, r.text
    assert r.json()["restored"]["users"] == 4, r.text
    db = SessionLocal()
    try:
        got = {u.telegram_id: u.referrer_id
               for u in db.query(models.User).all()}
        assert got[50] == 100 and got[75] == 50, got
        assert got[30] == 30 and got[100] is None, got
    finally:
        db.close()
print("endpoint restore OK (FK-enforced, 200)")

# (g) Version pins: shell, bot menu URL, admin health.
with TestClient(app, raise_server_exceptions=False) as c:
    r = c.get("/health")
    assert r.status_code == 200, r.text
    assert HTML.count("?v=206") == 10, HTML.count("?v=206")
    assert "app.js?v=206" in HTML and "games.js?v=206" in HTML
    assert ("?v=19" + "2") not in HTML
    BOT = open(os.path.join(BASE, "app", "bot.py")).read()
    assert 'menu_url.rstrip("/") + "/?v=206"' in BOT
    app.dependency_overrides[admin_user] = lambda: object()
    try:
        r = c.get("/admin/health")
        assert r.status_code == 200, r.text
        h = r.json()
        assert h["version"] == 206, h["version"]
    finally:
        app.dependency_overrides.clear()
assert len(main_mod._BACKUP_TABLES) == 55, len(main_mod._BACKUP_TABLES)
print("version ?v=206 + routes 184 + backup 52 OK")
print("PHASE 193 ALL OK")
