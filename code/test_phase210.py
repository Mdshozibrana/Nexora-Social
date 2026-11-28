"""Phase-210 tests: app PIN lock (owner model, Nov 27, 23:50-23:51).

First visit auto-logs in via Telegram as today. Once a 4-digit PIN
is set FROM SETTINGS, EVERY later app open shows the PIN card (the
owner's door-lock video, hubuhu same — white smart lock, 4 dots:
grey idle -> blue filled -> red error -> green success, handle
presses down on success, "Nexora Social" at the bottom of the
door) and the PIN unlocks it. PIN stored as a salted PBKDF2 hash,
never plaintext; 5 wrong tries lock the PIN for 5 minutes (never
permanent); forgot-PIN clears it after a fresh Telegram identity
check. Admin TOTP untouched. Plain script (run.sh runs it directly).
"""
import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase210.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import (  # noqa: E402
    app, _BACKUP_TABLES, _health_version, _pin_token_ok,
)
from app import models as _models  # noqa: E402
from app.db import SessionLocal as _SessionLocal  # noqa: E402

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
MAIN = open(os.path.join(ROOT, "code/app/main.py")).read()
MODELS = open(os.path.join(ROOT, "code/app/models.py")).read()
CONFIG = open(os.path.join(ROOT, "code/app/config.py")).read()
c = TestClient(app)

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


ALICE = H(111, "Alice")
BOB = H(222, "Bob")


def _reset_pin(uid):
    # Re-runs must start clean: clear any PIN state a previous run
    # left on this member's row (no-op when the row is absent).
    db = _SessionLocal()
    try:
        u = db.get(_models.User, uid)
        if u is not None:
            u.pin_hash = None
            u.pin_failed_count = 0
            u.pin_locked_until = None
            db.commit()
    finally:
        db.close()


def _row(uid):
    db = _SessionLocal()
    try:
        return db.get(_models.User, uid)
    finally:
        db.close()


def _clear_lock(uid):
    db = _SessionLocal()
    try:
        u = db.get(_models.User, uid)
        assert u is not None
        u.pin_locked_until = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()


# --- 1. Static: PIN lock client, styles, server, Nexa. ----------------
for m in ("showPinLock", "updatePinDots", "pinKey", "pinBackspace",
          "pinSubmit", "pinForgot", "buildPinLock", "pinLockTitle",
          "refreshPinDetail",
          "me.pin_required", "e.pinLocked", "pinLocked",
          "nx_pin_token", "sessionStorage.setItem(\"nx_pin_token\"",
          "sessionStorage.getItem(\"nx_pin_token\"",
          "settingsPinSet", "/me/pin/status", "app_pin",
          "settings-pin-state", "settings-pin-set",
          "settings-pin-remove", "App PIN",
          "app_pin: \"🔐 App PIN\"",
          "App PIN in Settings locks the app"):
    assert m in JS, f"missing JS marker: {m}"
# The video's updatePinDots, kept verbatim in shape.
assert "dot.className = \"pin-dot\"" in JS, "updatePinDots reset missing"
assert "dot.classList.add(\"success\")" in JS, "success dots missing"
assert "dot.classList.add(\"error\")" in JS, "error dots missing"
assert "dot.classList.add(\"filled\")" in JS, "filled dots missing"
# The brand sits at the bottom of the door.
assert "Nexora Social" in JS, "brand missing"
# The lock blocks the app (no close) but Settings flows close.
assert "pinCloseEl.hidden = pinMode === \"unlock\"" in JS
assert "pinForgotEl.hidden = pinMode !== \"unlock\"" in JS
# Boot gate: no heartbeat / entry paint before the lock clears.
assert "showPinLock(\"unlock\")" in JS, "boot lock call missing"
assert "if (me.pin_required)" in JS, "pin_required gate missing"
assert "if (err && err.pinLocked) return" in JS, "pinLocked swallow missing"
assert "if (err2 && err2.pinLocked) return" in JS, "retry pinLocked swallow missing"
# The media-token refresh carries the PIN token too.
assert "body: JSON.stringify({ initData, pinToken })" in JS
print("1. JS PIN lock markers OK")

for m in (".pin-lock {", ".pin-lockbody {", ".pin-display {",
          ".pin-dots {", ".pin-dot {", ".pin-dot.filled {",
          ".pin-dot.success {", ".pin-dot.error {",
          ".pin-rose {", ".pin-rose.pressed {", ".pin-handle {",
          ".pin-rose.pressed .pin-handle {",
          ".pin-slot {", ".pin-shake {", "@keyframes pinshake",
          ".pin-title {", ".pin-msg {", ".pin-keys {",
          ".pin-key {", ".pin-key-blank {", ".pin-forgot {",
          ".pin-brand {", "Phase 210: app PIN lock",
          "z-index: 200"):
    assert m in CSS, f"missing CSS marker: {m}"
print("1b. CSS PIN card markers OK")

for m in ("/me/pin/status", "/me/pin/set", "/me/pin/remove",
          "/me/pin/unlock", "/me/pin/forgot",
          "def _pin_hash", "def _pin_check", "def _pin_token",
          "def _pin_token_ok", "def _require_user_fresh",
          "pin_required", "\"pin_set\":",
          "class PinIn", "_pin_valid_format", "_pin_check_lock",
          "Too many wrong tries", "PIN locked for 5 minutes",
          "No PIN is set", "Current PIN is wrong",
          "APP PIN: a 4-digit PIN set from Settings",
          "Settings → App PIN"):
    assert m in MAIN, f"missing server marker: {m}"
assert "pin_hash" in MODELS and "pin_failed_count" in MODELS, \
    "model PIN columns missing"
assert "pin_locked_until" in MODELS, "model lockout column missing"
assert '"app_pin": (30, 3600)' in CONFIG, "app-PIN rate bucket missing"
assert "pbkdf2$200000$" in MAIN, "PBKDF2 hash format missing"
print("1c. server PIN markers OK")

# --- 2. Server: PIN lifecycle. ----------------------------------------
_reset_pin(111)
_reset_pin(222)

# 2a. No PIN yet: status false, /auth is the full me.
r = c.get("/me/pin/status", headers=ALICE)
assert r.status_code == 200, r.text
assert set(r.json().keys()) == {"pin_set"}, r.json()
assert r.json() == {"pin_set": False}, r.json()
r = c.post("/auth", json={"initData": make_init_data(
    {"id": 111, "first_name": "Alice"})})
assert r.status_code == 200, r.text
assert "pin_required" not in r.json(), r.json()
assert r.json()["pin_set"] is False, r.json()
assert r.json()["media_token"], "media token missing pre-PIN"
print("2a. no PIN: status false, /auth full OK")

# 2b. Bad formats rejected; a good PIN sets it — hashed, not plain.
for bad in ("123", "12345", "abcd", "12 4", ""):
    r = c.post("/me/pin/set", headers=ALICE, json={"pin": bad})
    assert r.status_code == 400, (bad, r.text)
r = c.post("/me/pin/set", headers=ALICE, json={"pin": "1234"})
assert r.status_code == 200 and r.json() == {"pin_set": True}, r.text
row = _row(111)
assert row.pin_hash and row.pin_hash != "1234", "PIN stored in plaintext?"
assert row.pin_hash.startswith("pbkdf2$200000$"), row.pin_hash
assert "1234" not in json.dumps(c.get(
    "/me/pin/status", headers=ALICE).json()), "PIN leaked in status"
print("2b. format guards + salted hash OK")

# 2c. /auth gates: no token -> pin_required with NO user data.
r = c.post("/auth", json={"initData": make_init_data(
    {"id": 111, "first_name": "Alice"})})
assert r.status_code == 200, r.text
assert r.json() == {"pin_required": True}, r.json()
assert "media_token" not in r.json(), "gated /auth leaked a token"
# A token minted for someone else does not open this account.
tok_alice = c.post("/me/pin/unlock", headers=ALICE,
                   json={"pin": "1234"}).json()["pin_token"]
assert _pin_token_ok(tok_alice) == 111, "token must verify to 111"
r = c.post("/auth", json={"initData": make_init_data(
    {"id": 222, "first_name": "Bob"}), "pinToken": tok_alice})
assert r.status_code == 200, r.text
assert r.json()["pin_set"] is False, "Bob has no PIN — token is moot"
print("2c. /auth gate + token binding OK")

# 2d. Wrong tries count down; the 5th locks for 5 minutes.
for tries_left in (4, 3, 2, 1):
    r = c.post("/me/pin/unlock", headers=ALICE, json={"pin": "9999"})
    assert r.status_code == 400, r.text
    assert f"{tries_left} tries left" in r.text, r.text
r = c.post("/me/pin/unlock", headers=ALICE, json={"pin": "9999"})
assert r.status_code == 429 and "5 minutes" in r.text, r.text
r = c.post("/me/pin/unlock", headers=ALICE, json={"pin": "1234"})
assert r.status_code == 429, "locked PIN must refuse the right PIN too"
_clear_lock(111)
r = c.post("/me/pin/unlock", headers=ALICE, json={"pin": "1234"})
assert r.status_code == 200 and r.json().get("pin_token"), r.text
# A correct unlock resets the count: the next wrong try is 4 left.
r = c.post("/me/pin/unlock", headers=ALICE, json={"pin": "9999"})
assert r.status_code == 400 and "4 tries left" in r.text, r.text
print("2d. lockout (5 tries, 5 min, never permanent) OK")

# 2e. Change needs the current PIN; the old PIN dies, the new works.
r = c.post("/me/pin/set", headers=ALICE, json={"pin": "5678"})
assert r.status_code == 400 and "Current PIN" in r.text, r.text
r = c.post("/me/pin/set", headers=ALICE,
           json={"pin": "5678", "current_pin": "0000"})
assert r.status_code == 400 and "Current PIN" in r.text, r.text
r = c.post("/me/pin/set", headers=ALICE,
           json={"pin": "5678", "current_pin": "1234"})
assert r.status_code == 200 and r.json() == {"pin_set": True}, r.text
r = c.post("/me/pin/unlock", headers=ALICE, json={"pin": "1234"})
assert r.status_code == 400, "old PIN must stop working"
r = c.post("/me/pin/unlock", headers=ALICE, json={"pin": "5678"})
assert r.status_code == 200 and r.json().get("pin_token"), r.text
print("2e. change-PIN guards OK")

# 2f. Remove needs the current PIN; after removal /auth is open again.
r = c.post("/me/pin/remove", headers=ALICE, json={"current_pin": "0000"})
assert r.status_code == 400 and "Current PIN" in r.text, r.text
r = c.post("/me/pin/remove", headers=ALICE, json={"current_pin": "5678"})
assert r.status_code == 200 and r.json() == {"pin_set": False}, r.text
r = c.post("/auth", json={"initData": make_init_data(
    {"id": 111, "first_name": "Alice"})})
assert r.status_code == 200 and "pin_required" not in r.json(), r.json()
r = c.post("/me/pin/unlock", headers=ALICE, json={"pin": "5678"})
assert r.status_code == 400 and "No PIN is set" in r.text, r.text
print("2f. remove-PIN guards OK")

# 2g. Forgot: stale identity refused, fresh identity clears the PIN.
r = c.post("/me/pin/set", headers=ALICE, json={"pin": "2468"})
assert r.status_code == 200, r.text
r = c.post("/me/pin/forgot", headers=H(
    111, "Alice", auth_date=int(time.time()) - 400))
assert r.status_code == 401, r.text
r = c.get("/me/pin/status", headers=ALICE)
assert r.json() == {"pin_set": True}, "stale forgot must not clear"
r = c.post("/me/pin/forgot", headers=ALICE)
assert r.status_code == 200 and r.json() == {"pin_set": False}, r.text
r = c.post("/auth", json={"initData": make_init_data(
    {"id": 111, "first_name": "Alice"})})
assert r.status_code == 200 and "pin_required" not in r.json(), r.json()
print("2g. forgot-PIN (fresh identity only) OK")

# 2h. Tokens: tampered and expired tokens verify to None.
assert _pin_token_ok("bogus") is None, "bogus token must fail"
exp = int(time.time()) - 10
sig = hmac.new(b"123456789:AAE" + b"x" * 32,
               f"nexora-pin:111:{exp}".encode(),
               hashlib.sha256).hexdigest()
tok = base64.urlsafe_b64encode(f"111.{exp}.{sig}".encode()).decode()
assert _pin_token_ok(tok) is None, "expired token must fail"
# Another member's PIN state is theirs alone; the public profile
# never carries PIN fields.
r = c.get("/me/pin/status", headers=BOB)
assert r.json() == {"pin_set": False}, r.json()
r = c.post("/me/pin/unlock", headers=BOB, json={"pin": "1234"})
assert r.status_code == 400 and "No PIN is set" in r.text, r.text
r = c.get("/users/111", headers=BOB)
assert r.status_code == 200, r.text
for k in ("pin_hash", "pin_set", "pin_locked", "pin_failed"):
    assert k not in r.text, f"PIN field leaked on public profile: {k}"
print("2h. token checks + no cross-user / profile leak OK")

# --- 3. Version pins + routes + backup + health. ----------------------
assert HTML.count("?v=211") == 10, HTML.count("?v=211")
assert "?v=20" + "9" not in HTML
assert "app.js?v=211" in HTML and "games.js?v=211" in HTML
assert "style.css?v=211" in HTML
assert 'menu_url.rstrip("/") + "/?v=211"' in BOT
assert ("/?v=20" + "9") not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 196, len(paths)
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert _health_version() == 211, _health_version()
print("3. version ?v=211, routes 196, backup 55, health 210 OK")

# --- 4. Node harness: the real app.js PIN card. ----------------------
r = subprocess.run(["node",
                    os.path.join(DESIGNS, "phase210_pin_proof.js"),
                    os.path.join(ROOT, "code/webapp/app.js")],
                   capture_output=True, text=True, cwd=ROOT)
assert r.returncode == 0, r.stdout + r.stderr
assert "DONE failures=0" in r.stdout, r.stdout
print("4. node PIN harness OK")

# --- 5. Served assets: version + markers. -----------------------------
html = c.get("/webapp/").text
assert html.count("?v=211") == 10, html.count("?v=211")
assert "?v=20" + "9" not in html
served_js = c.get("/webapp/app.js").text
for marker in ("showPinLock", "updatePinDots", "pinToken",
               "me.pin_required", "Nexora Social", "App PIN"):
    assert marker in served_js, marker
css = c.get("/webapp/style.css").text
for marker in ("Phase 210: app PIN lock", ".pin-lockbody",
               ".pin-dot.success", ".pin-rose.pressed", ".pin-brand"):
    assert marker in css, marker
print("5. served assets ?v=211 + markers OK")

print("PHASE 210 OK (app PIN lock)")
