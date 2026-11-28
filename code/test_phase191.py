"""Phase 191 tests: database connection-pool leak at its root.

DIAGNOSIS (proven, not assumed):
- Nov 26, 21:13-21:23 Dhaka the service wedged: SQLAlchemy
  "QueuePool limit of size 5 overflow 10 reached, connection timed
  out, timeout 30.00" — all 15 pool connections checked out and
  not returning; the TimeoutError surfaced in media_proxy at
  main.py:9117 (viewer = db.get(...)), i.e. waiting on CHECKOUT.
  The process never crashed, the dashboard showed "Live", the DB
  was healthy. A dashboard restart at ~21:35 fixed it.
- Root cause is a HOLD: media_proxy took Depends(get_db) and
  returned a StreamingResponse, and FastAPI closes a
  yield-dependency only AFTER the response body is fully sent —
  so every /media request held a pool connection for the whole
  Telegram download + client stream (up to 90s). A gallery page
  fires ~10 concurrent /media requests and wedged the pool.
FIX: media_proxy opens a short-lived session (db.short_session())
  ONLY for the auth + visibility checks, then closes it BEFORE
  the Telegram fetch and the stream. The stream holds NO database
  connection. Pool sizing is explicit (5/10/30/recycle 1800,
  Postgres only) and GET /admin/health reports live pool gauges,
  rendered on the Admin Panel System Health card.
The wedge scenario below FAILS on the old code (a connection is
checked out for the whole slow stream, so two slow streams wedge
a 2-connection pool and a third request cannot get one) and
PASSES on the new code (no connection is held while streaming).
Plain script (run.sh runs it with python directly).
"""
import asyncio
import os
import subprocess
import threading

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
DB_PATH = os.path.expanduser(
    "~/workspace/nexora_run69/test_phase191.sqlite")
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import httpx  # noqa: E402
import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

# --- Telegram upstream, faked per file_id -------------------------
# SLOW streams 6 chunks with 0.8s between them (~4s after the first
# chunk — longer than the tiny pool's 2s checkout timeout, so on the
# OLD code a third request fails while the streams are still in
# flight instead of racing them to the finish). FAST streams at once.
# DEAD 404s at getFile.


class FakeGetFileResp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {"ok": True,
                              "result": {"file_path": "photos/file_1.jpg"}}

    def json(self):
        return self._body


class FakeStreamResp:
    status_code = 200

    def __init__(self, slow=False):
        self._slow = slow

    @property
    def headers(self):
        return {"content-type": "image/jpeg",
                "content-length": "12" if self._slow else "4"}

    async def aiter_bytes(self):
        if self._slow:
            yield b"S1"
            for chunk in (b"S2", b"S3", b"S4", b"S5", b"S6"):
                await asyncio.sleep(0.8)
                yield chunk
        else:
            yield b"F1"
            yield b"F2"

    async def aclose(self):
        pass


class FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        fid = (params or {}).get("file_id", "")
        if fid == "DEAD":
            return FakeGetFileResp(
                404, {"ok": False,
                      "description": "Bad Request: file not found"})
        path = "photos/slow.jpg" if fid == "SLOW" else "photos/fast.jpg"
        return FakeGetFileResp(
            200, {"ok": True, "result": {"file_path": path}})

    def build_request(self, method, url, headers=None):
        return (method, url, headers)

    async def send(self, req, stream=False):
        return FakeStreamResp(slow=("slow" in req[1]))

    async def aclose(self):
        pass


httpx.AsyncClient = FakeAsyncClient

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import QueuePool  # noqa: E402
from app import db as db_mod  # noqa: E402
from app.main import _media_token, admin_user, app  # noqa: E402
from app import models  # noqa: E402
from app.users import get_or_create_user  # noqa: E402

# --- Tiny pool: 2 connections, no overflow, 2s checkout timeout --
# On the OLD code two concurrent slow streams take both connections
# and a third request times out waiting for one; on the NEW code
# no stream holds a connection at all.
tiny = create_engine(
    "sqlite:///" + DB_PATH, connect_args={"check_same_thread": False},
    poolclass=QueuePool, pool_size=2, max_overflow=0, pool_timeout=2)
db_mod.engine = tiny
db_mod.SessionLocal = sessionmaker(bind=tiny, autoflush=False,
                                   autocommit=False)

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
MAIN_SRC = open(os.path.join(ROOT, "code/app/main.py")).read()
DB_SRC = open(os.path.join(ROOT, "code/app/db.py")).read()

# --- Seed: user + two visible design files ------------------------
with db_mod.SessionLocal() as db:
    get_or_create_user(
        db, {"id": 1911, "username": "alice191", "first_name": "Alice"})
    db.query(models.Design).delete()
    db.add(models.Design(image_file_id="SLOW", prompt="slow one"))
    db.add(models.Design(image_file_id="FAST", prompt="fast one"))
    db.commit()

TOKEN = _media_token(1911)
assert TOKEN
c = TestClient(app, raise_server_exceptions=False)


def slow_stream(results, idx, started_evt):
    """One slow /media stream in its own client/thread; reports
    (status, body) and sets started_evt after the first chunk."""
    try:
        # No `with` on the client: entering TestClient runs the app
        # lifespan, which starts the sweeper/auto-backup tasks on
        # this thread's portal; tearing that portal down mid-stream
        # raises a cross-loop RuntimeError. Requests work fine
        # without the lifespan (as in test_phase189).
        tc = TestClient(app, raise_server_exceptions=False)
        with tc.stream("GET", "/media/SLOW?mt=" + TOKEN) as r:
                assert r.status_code == 200, r.text
                it = r.iter_bytes()
                first = next(it)
                assert first == b"S1", first
                started_evt.set()
                body = first + b"".join(it)
                results[idx] = (200, body)
    except Exception as e:  # noqa: BLE001 - reported, asserted below
        results[idx] = ("error", repr(e))


# --- 1. Wedge repro: slow streams must hold NO connection ---------
results = [None, None]
evts = [threading.Event(), threading.Event()]
threads = [threading.Thread(target=slow_stream,
                            args=(results, i, evts[i]), daemon=True)
           for i in range(2)]
for t in threads:
    t.start()
assert evts[0].wait(10) and evts[1].wait(10), \
    "slow streams did not start"
# Sharp assertion: while two slow streams are in flight, the pool
# must show ZERO checked out — on the old code it shows 2 (one
# get_db session per stream, held until the stream finishes).
co = tiny.pool.checkedout()
assert co == 0, f"pool checked out during streams: {co} (old code " \
    "holds one connection per /media stream)"
# Wedge assertion: a third request must succeed while the streams
# are still running — on the old code it waits pool_timeout=2s for
# a connection and answers 500.
r = c.get("/media/FAST?mt=" + TOKEN)
assert r.status_code == 200, r.text
assert r.content == b"F1F2", r.content
for t in threads:
    t.join(15)
assert not any(t.is_alive() for t in threads), \
    "slow stream threads did not finish"
assert results[0] == (200, b"S1S2S3S4S5S6"), results[0]
assert results[1] == (200, b"S1S2S3S4S5S6"), results[1]
assert tiny.pool.checkedout() == 0, "pool did not drain after streams"
print("wedge repro OK (slow streams hold 0 connections; third "
      "request succeeds mid-stream; pool drains to 0)")

# --- 2. Source markers --------------------------------------------
assert "async def media_proxy(file_id: str, request: Request):" \
    in MAIN_SRC, "media_proxy still takes a request-scoped session"
mi = MAIN_SRC.index("async def media_proxy")
mj = MAIN_SRC.index("if WEBAPP_DIR.exists():", mi)
proxy = MAIN_SRC[mi:mj]
assert "with short_session() as db:" in proxy, \
    "media_proxy does not use a short-lived session"
# Before the docstring: the signature must not take get_db (the
# Phase 191 comment below mentions the old pattern by name, so
# the check is scoped to the signature, not the whole span).
assert "Depends(get_db)" not in proxy.split('"""')[0], \
    "media_proxy still depends on get_db"
assert "set_rls_context_for(" in proxy and "apply_rls_context(" in proxy, \
    "media_proxy lost its RLS binding (Phase 186 pins)"
assert "clear_rls_context()" in proxy, \
    "media_proxy does not clear the RLS context"
assert 'headers["cache-control"] = "private, max-age=3600, immutable"' \
    in proxy, "media_proxy lost its cache header (Phase 111)"
assert "def short_session" in DB_SRC, "short_session missing in db.py"
assert "pool_recycle=1800" in DB_SRC, "pool_recycle missing in db.py"
assert "pool_size=5" in DB_SRC and "max_overflow=10" in DB_SRC, \
    "explicit pool sizing missing in db.py"
assert "def pool_status" in DB_SRC, "pool_status missing in db.py"
assert '"pool": pool_status()' in MAIN_SRC, \
    "admin health does not report pool gauges"
assert "poolText(h.pool)" in JS, "health card does not render pool gauges"
assert "function poolText" in JS, "poolText helper missing in app.js"
print("source markers OK (short session + pool sizing + gauges)")

# --- 3. Pool health endpoint --------------------------------------
app.dependency_overrides[admin_user] = lambda: object()
try:
    r = c.get("/admin/health")
    assert r.status_code == 200, r.text
    h = r.json()
    assert "pool" in h, h.keys()
    pool = h["pool"]
    assert set(pool.keys()) == {"size", "checkedin", "checkedout",
                                "overflow"}, pool
    assert pool["size"] == 2, pool  # the tiny test pool
    assert pool["checkedout"] >= 1, pool  # this very request holds one
    assert pool["checkedin"] + pool["checkedout"] <= pool["size"], pool
    assert pool["overflow"] == 0, pool
finally:
    app.dependency_overrides.clear()
assert tiny.pool.checkedout() == 0, "pool did not drain after /health"
print("pool health OK (gauges live on /admin/health, drain at rest)")

# --- 4. JS parses + version pins ----------------------------------
for f in ("webapp/app.js", "webapp/games.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True,
                       cwd=os.path.join(ROOT, "code"))
    assert r.returncode == 0, (f, r.stderr)
assert HTML.count("?v=209") == 10, HTML.count("?v=209")
assert "app.js?v=209" in HTML and "games.js?v=209" in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert 'menu_url.rstrip("/") + "/?v=209"' in BOT
assert h["version"] == 209, h["version"]
print("version ?v=209 + routes 184 + backup 52 OK")
print("PHASE 191 ALL OK")
