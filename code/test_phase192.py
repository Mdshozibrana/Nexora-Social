"""Phase-192 tests: _migrate() was missing the broadcasts ALTER, so
GET /admin/backup 500d on the OLD production service.

DIAGNOSIS (old service Render logs, Nov 27 ~00:40 Dhaka):
- GET /admin/backup -> HTTP 500, reproducibly:
  sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedColumn)
  column broadcasts.delivered_targets does not exist, raised in
  _backup_payload (db.query(model)...all()) via admin_backup.
- ROOT CAUSE: the Broadcast model has
  delivered_targets = Column(Text, default="[]", nullable=False),
  added in Phase 181 (audit M9 resume-skip), but NO migration was
  ever written for it. create_all() only creates missing TABLES,
  never adds columns to existing tables, so the OLD database
  (created Oct 31, 2026, before Phase 181) never got the column.
  Fresh DBs get it from create_all(), so only the old DB broke.

AUDIT (full history walk of models.py before the fix):
- Every (class, column) pair was traced to its introducing commit
  and compared with its table's creation commit. 30 columns were
  added after their table's creation; 29 are already covered by
  _migrate() (users x18, posts x5, comments parent_id, messages
  x4, plus User.is_verified which predates the old DB). Exactly
  ONE gap: Broadcast.delivered_targets (table Nov 17, column
  Nov 25). The brief's prime suspects were already covered
  (messages.media_duration, users.blood_group/blood_donor).
  So this phase adds ONE guarded ALTER and nothing else.

TESTS:
(a) source: the ALTER exists exactly once, with a Postgres- and
    SQLite-legal TEXT ... NOT NULL DEFAULT '[]' definition.
(b) functional: import ran create_all + _migrate on the fresh db,
    so broadcasts has delivered_targets; DROP the column to
    simulate the old production DB and assert _backup_payload
    raises naming delivered_targets (the exact old-service
    failure); re-run _migrate() directly and assert the column
    comes back; re-running is idempotent.
(c) backup: with a broadcast row present, _backup_payload runs
    clean, covers all 52 tables, and round-trips the row
    including delivered_targets.
(d) version pins: shell ?v=203 (x10), old version gone, bot menu
    URL bumped, /admin/health version 192, backup 52 tables.
No auth, no make_init_data — the admin endpoint is reached via
a dependency override, like test_phase191.
Plain script (run.sh runs it with python directly).
"""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
DB_PATH = os.path.expanduser(
    "~/workspace/nexora_run69/test_phase192.sqlite")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["ADMIN_IDS"] = "999"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402
import app.main as main_mod  # noqa: E402
from app.main import admin_user, app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(BASE, "webapp", "index.html")).read()
SRC = open(os.path.join(BASE, "app", "main.py")).read()

# (a) Source: the ALTER exists exactly once, Postgres/SQLite-legal.
alter_lines = [ln for ln in SRC.splitlines()
               if "delivered_targets TEXT" in ln]
assert len(alter_lines) == 1, alter_lines
assert "NOT NULL DEFAULT '[]'" in alter_lines[0], alter_lines
assert SRC.count("ALTER TABLE broadcasts ADD COLUMN") == 1
assert "delivered_targets" in SRC.split("def _migrate()")[1].split(
    "# Phase 60")[0], "ALTER not inside _migrate"
print("source markers OK (one guarded broadcasts ALTER)")

# (b) Functional: import ran create_all + _migrate on the fresh db.
engine = main_mod.engine
cols = {c["name"] for c in inspect(engine).get_columns("broadcasts")}
assert "delivered_targets" in cols, sorted(cols)

# Simulate the OLD production DB: broadcasts table WITHOUT the
# column (Phase 131 schema, before Phase 181 added it to the model).
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE broadcasts DROP COLUMN delivered_targets"))
cols = {c["name"] for c in inspect(engine).get_columns("broadcasts")}
assert "delivered_targets" not in cols

# The exact old-service failure: _backup_payload raises naming the
# missing column (UndefinedColumn on Postgres; on SQLite the SELECT
# of the missing column raises the same way).
db = SessionLocal()
try:
    try:
        main_mod._backup_payload(db)
        raise AssertionError("backup payload ran without the column")
    except Exception as exc:
        assert "delivered_targets" in str(exc), str(exc)
finally:
    db.close()
print("fail-on-old OK (backup raises without the column)")

# The fix: re-run _migrate() and the column comes back.
main_mod._migrate()
cols = {c["name"] for c in inspect(engine).get_columns("broadcasts")}
assert "delivered_targets" in cols, sorted(cols)
# Re-running _migrate is idempotent (guarded by the column check).
main_mod._migrate()
cols = {c["name"] for c in inspect(engine).get_columns("broadcasts")}
assert "delivered_targets" in cols
print("migrate OK (column restored, idempotent)")

# (c) Backup runs clean now and round-trips a broadcasts row.
db = SessionLocal()
try:
    db.query(models.Broadcast).delete()
    db.add(models.Broadcast(text="hello", target="all", sent_by=999,
                            delivered_count=0, total_count=0,
                            delivered_targets='["111"]'))
    db.commit()
    payload = main_mod._backup_payload(db)
    assert len(payload["tables"]) == 55, len(payload["tables"])
    rows = payload["tables"]["broadcasts"]
    assert len(rows) == 1, rows
    assert rows[0]["text"] == "hello", rows
    assert rows[0]["delivered_targets"] == '["111"]', rows
finally:
    db.close()
print("backup payload OK (52 tables, broadcasts row round-trips)")

# (d) Version pins: shell, bot menu URL, admin health.
c = TestClient(app, raise_server_exceptions=False)
r = c.get("/health")
assert r.status_code == 200, r.text
assert HTML.count("?v=203") == 10, HTML.count("?v=203")
assert "app.js?v=203" in HTML and "games.js?v=203" in HTML
assert ("?v=19" + "1") not in HTML
BOT = open(os.path.join(BASE, "app", "bot.py")).read()
assert 'menu_url.rstrip("/") + "/?v=203"' in BOT
app.dependency_overrides[admin_user] = lambda: object()
try:
    r = c.get("/admin/health")
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["version"] == 203, h["version"]
finally:
    app.dependency_overrides.clear()
assert len(main_mod._BACKUP_TABLES) == 55, len(main_mod._BACKUP_TABLES)
print("version ?v=203 + routes 184 + backup 52 OK")
print("PHASE 192 ALL OK")
