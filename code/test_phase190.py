"""Phase 190 tests: boot watchdog — the app must never sit on
"Loading…" forever when the server is unreachable.

Diagnosis (proven in the phase, not assumed):
- Nov 26, 21:13-21:23 Dhaka the service wedged: SQLAlchemy pool
  exhausted (5 + 10 overflow, all checked out, 30s timeouts in
  media_proxy, main.py:9117). /health, shell and app.js all timed
  out (http=000, 0 bytes, even at 120s); the dashboard showed
  "Live"; no deploy/crash events; DB healthy. Restarted from the
  dashboard ~21:35 Dhaka; verified back (health 200 in 0.88s,
  shell 10x?v=189, app.js 454,957 B).
- The user saw "only Loading": with the server wedged, either the
  shell never arrives (Telegram's own loading spinner forever) or
  the shell/app.js arrive from cache and loadMe()'s /auth fetch —
  which had NO timeout (api() only aborts when timeoutMs is
  passed, and only the assistant call used it) — hangs forever,
  and bootFailed's else branch then says "open from inside
  Telegram" with a DISABLED button even though Telegram IS
  present. There was no bounded failure path at all.
Fix: an inline boot watchdog in index.html (before the vendor /
app.js script tags, so it runs even when app.js never arrives)
shows "Could not reach the server…" + a working RETRY if the app
has not signalled a boot outcome within 60s of the shell parsing;
bootOk()/bootFailed() disarm it via window.__nxBootDone; /auth
gets a bounded 25s timeout (loadMe + refreshMediaToken); api()
keeps the HTTP status on thrown errors, and bootFailed(err) shows
the server message + enabled RETRY for a dead server (abort /
TypeError / 5xx) while keeping the old "open from inside
Telegram" branch for a refused login (401) and the Telegram
message for a missing Telegram script.
The harness (nexora_designs/phase190_boot_proof.js) FAILS on the
old ?v=189 code (watchdog block absent; hung /auth never reaches
bootFailed; a 503 shows the outside-Telegram line) and passes all
6 modes on the new code — run it here against the local files.
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = (
    "sqlite:///" + os.path.expanduser(
        "~/workspace/nexora_run69/test_phase190.sqlite"))
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES  # noqa: E402
from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402


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


ALICE = H(1901, "Alice", "alice190")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()

c = TestClient(app)

# --- 1. JS parses (node) ------------------------------------------
for f in ("webapp/app.js", "webapp/games.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True,
                       cwd=os.path.join(ROOT, "code"))
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (app.js + games.js parse)")

# --- 2. Harness: all 6 modes pass on new code, fail on old --------
HARNESS = os.path.join(DESIGNS, "phase190_boot_proof.js")
for mode, marker in (
        ("watchdog", "WATCHDOG_OK"),
        ("auth-hang", "AUTH-HANG_OK"),
        ("auth-typeerror", "AUTH-TYPEERROR_OK"),
        ("auth-503", "AUTH-503_OK"),
        ("auth-401", "AUTH-401_OK"),
        ("no-telegram", "NO-TELEGRAM_OK")):
    r = subprocess.run(["node", HARNESS, mode],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (mode, r.stdout + r.stderr)
    assert marker in r.stdout, (mode, r.stdout)
print("boot harness OK (6/6: watchdog + hung/typeerror/503/401/no-telegram)")

# --- 3. Shell watchdog: inline, before app.js, 60s, RETRY ---------
assert "__nxBootWatchdog" in HTML, "no inline watchdog in shell"
assert HTML.index("__nxBootWatchdog") < HTML.index("app.js?v=198"), \
    "watchdog must precede the app.js script tag"
wd = HTML[HTML.index("// Phase 190: boot watchdog"):]
wd = wd[:wd.index("</script>")]
assert "60000" in wd, "watchdog has no 60s bound"
assert "Could not reach the server" in wd, "no server message"
assert "The server did not answer" in wd, "no server note"
assert '"↻ RETRY"' not in wd, "watchdog must use the \\u21bb escape"
assert "\\u21bb RETRY" in wd, "no RETRY label"
assert "location.reload()" in wd, "RETRY does not reload"
assert "window.__nxBootDone" in wd, "watchdog reads no disarm flag"
print("shell watchdog OK (inline before app.js, 60s, server + RETRY)")

# --- 4. Client markers: disarm, bounded /auth, server branch ------
assert JS.count("window.__nxBootDone = true;") == 2, \
    JS.count("window.__nxBootDone = true;")
at = JS.index("function bootOk() {")
assert 'setStatus("");' in JS[at:at + 600], "bootOk does not clear #status"
at = JS.index('me = await api("/auth"')
assert "timeoutMs: 25000" in JS[at:at + 200], "loadMe /auth has no timeout"
at = JS.index('const r = await api("/auth"')
assert "timeoutMs: 25000" in JS[at:at + 200], \
    "refreshMediaToken /auth has no timeout"
assert "function bootFailed(err)" in JS, "bootFailed takes no error"
assert "err.status = res.status" in JS, "api() keeps no status on errors"
assert '(err.status && err.status >= 500)' in JS, "no 5xx branch"
assert 'err.name === "AbortError"' in JS, "no abort branch"
assert "err instanceof TypeError" in JS, "no TypeError branch"
assert "Could not reach the server" in JS, "no server message in app.js"
assert "The server did not answer" in JS, "no server note in app.js"
assert "Please open this app from inside Telegram." in JS, \
    "outside-Telegram branch lost"
assert "Could not reach Telegram" in JS, "Telegram branch lost"
# The Phase 76 retry-once chain is unchanged.
assert "loadMe().then(bootOk).catch(bootFailed)" in JS
assert JS.count("loadMe().then(bootOk)") == 2
print("client markers OK (disarm x2 + 25s /auth + server branch)")

# --- 5. Server: /auth still works (the boot path, end to end) -----
r = c.post("/auth", json={"initData": make_init_data(
    {"id": 1901, "first_name": "Alice", "username": "alice190"})})
assert r.status_code == 200, r.text
assert r.json()["media_token"], "no media token from /auth"
print("auth OK (loadMe path answers 200 + media token)")

# --- 6. Keepalive: the saved job really pings with -m 60 ----------
# Phase 188's file edit never reached the saved job (it still ran
# -m 25); the parent fixed it via cron.update — pin the file.
KEEPALIVE = os.path.expanduser(
    "~/workspace/goals/friend-line-style-telegram-social-platform"
    "/crons/minutely/nexora-keepalive__interval@10m.md")
kb = open(KEEPALIVE).read()
assert "curl -s -o /dev/null -m 60 " in kb, "keepalive still -m 25"
assert "-m 25" not in kb, "keepalive still mentions -m 25"
print("keepalive OK (saved job pings with -m 60)")

# --- 7. Version + routes + backup pins ------------------------------
assert HTML.count("?v=198") == 10, HTML.count("?v=198")
assert "?v=18" + "9" not in HTML
assert "app.js?v=198" in HTML and "games.js?v=198" in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert 'menu_url.rstrip("/") + "/?v=198"' in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 184, len(paths)
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
with TestClient(app) as cx:
    r = cx.get("/admin/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["version"] == 198, h["version"]
print("version ?v=198 + routes 184 + backup 52 OK")

print("PHASE 190 OK")
