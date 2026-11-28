"""Phase-126 tests: migration hotfix — is_pinned BOOLEAN DEFAULT 0.

Root cause (Render deploy logs, Nov 17): _migrate() ran
  ALTER TABLE posts ADD COLUMN is_pinned BOOLEAN DEFAULT 0
and Postgres rejected integer 0 as a boolean column default
(DatatypeMismatch), crashing the app at startup — all three Render
auto-deploys (123/124/125) failed with "Exited with status 1"
even though the build succeeded. The suites use SQLite, which
accepts DEFAULT 0, so all 121 suites passed while production
could not boot.

Fix (one line, code/app/main.py:105): DEFAULT 0 -> DEFAULT FALSE.
No feature code, theme, or other migration changes.

Tests: (a) source asserts the buggy pattern is gone and the ALTER
carries DEFAULT FALSE; (b) functional — import app.main on a fresh
sqlite file (create_all + _migrate run at import), assert the posts
table has is_pinned, drop the column, re-run _migrate() directly
and assert the patched ALTER re-adds it; (c) asset version ?v=210
(x5), ?v=125 gone; (d) Phase 123-125 client markers intact.
No auth, no make_init_data — none needed here.
"""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase126.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402
import app.main as main_mod  # noqa: E402
from app.main import app  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(BASE, "webapp", "index.html")).read()
JS = open(os.path.join(BASE, "webapp", "app.js")).read()
SRC = open(os.path.join(BASE, "app", "main.py")).read()

with TestClient(app) as c:
    r = c.get("/health")
    assert r.status_code == 200, r.text

# (a) Source: no BOOLEAN column with an integer default anywhere,
# and the is_pinned ALTER carries DEFAULT FALSE.
assert "BOOLEAN DEFAULT 0" not in SRC, "buggy pattern still present"
pinned_line = [ln for ln in SRC.splitlines() if "is_pinned BOOLEAN" in ln]
assert len(pinned_line) == 1, pinned_line
assert "DEFAULT FALSE" in pinned_line[0], pinned_line
# The INTEGER defaults elsewhere are fine and untouched.
assert SRC.count("repost_count INTEGER DEFAULT 0") == 2, \
    SRC.count("repost_count INTEGER DEFAULT 0")

# (b) Functional: import ran create_all + _migrate on the fresh db.
engine = main_mod.engine
cols = {c["name"] for c in inspect(engine).get_columns("posts")}
assert "is_pinned" in cols, sorted(cols)
# Exercise the patched ALTER itself: drop the column, re-run
# _migrate(), and assert it comes back via the fixed statement.
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE posts DROP COLUMN is_pinned"))
cols = {c["name"] for c in inspect(engine).get_columns("posts")}
assert "is_pinned" not in cols
main_mod._migrate()
cols = {c["name"] for c in inspect(engine).get_columns("posts")}
assert "is_pinned" in cols, sorted(cols)
# Re-running _migrate is idempotent (guarded by the column check).
main_mod._migrate()
cols = {c["name"] for c in inspect(engine).get_columns("posts")}
assert "is_pinned" in cols

# (c) Asset version bumped to ?v=210 (x5), ?v=125 gone from the shell.
assert HTML.count("?v=210") == 10, HTML.count("?v=210")
assert "?v=125" not in HTML
assert "app.js?v=210" in HTML and "style.css?v=210" in HTML

# (d) Phase 123-125 client markers intact in the served files.
for marker in ("topScroller", "pollBlock", "loadDrafts",
               "renderPh", "goFeedTo", "loadTrending"):
    assert marker in JS, marker

print("phase126: source + migration + ?v=210 + markers OK")
