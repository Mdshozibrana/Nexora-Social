"""Phase 188 tests: (1) boot guard — the app must not die blank when
telegram-web-app.js fails to load; (2) Help & Support page in the
Settings hub; (3) Settings button moved from Me to the sidebar.

Job 1 regression: the old `const tg = window.Telegram.WebApp;` threw
when window.Telegram was undefined and killed the whole script before
any UI painted (blank page = "the whole site doesn't load"). Proven
in Node with window.Telegram missing. The fix is a no-op stub fallback
plus bootFailed explaining the failure with a working RETRY (reload).
The boot harness (nexora_designs/phase188_boot_proof.js) runs the
served app.js in Node with Telegram missing and must reach the entry
screen with the RETRY message instead of throwing.
Job 2: Help row in SUPPORT above About; FAQ with real facts only, no
contact details; "Ask Nexa" opens the assistant; "Report a problem"
opens a DM to Nexora Social (id 1) — the admin reads it.
Job 3: the Settings button is gone from Me; the sidebar entry (ACCOUNT
section, data-go="settings") is the way in.
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.expanduser(
    "~/workspace/nexora_run69/test_phase188.sqlite")
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


ALICE = H(1881, "Alice", "alice188")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
CRON = open(os.path.join(
    os.path.expanduser("~/workspace/goals"),
    "friend-line-style-telegram-social-platform/crons/minutely",
    "nexora-keepalive__interval@10m.md")).read()

c = TestClient(app)

# --- 1. JS parses (node) — the boot guard touched the top of app.js,
# so a syntax slip would kill the whole shell, not just Settings.
for f in ("webapp/app.js", "webapp/games.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True,
                       cwd=os.path.join(ROOT, "code"))
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (app.js + games.js parse)")

# --- 2. Job 1: boot guard ---------------------------------------------
# The old unguarded line is gone; the stub fallback is in its place.
assert "const tg = window.Telegram.WebApp;" not in JS, \
    "unguarded Telegram dereference still present (blank-page bug)"
assert "(window.Telegram && window.Telegram.WebApp) || {" in JS
assert "BackButton: null, LocationManager: null" in JS
assert "Could not reach Telegram" in JS, "bootFailed has no Telegram case"
assert "RETRY" in JS and "location.reload()" in JS, "no working RETRY"
# The boot harness runs the real app.js in Node with window.Telegram
# missing: it must NOT throw at line 4 — it must reach the entry
# screen with the RETRY message.
r = subprocess.run(
    ["node", os.path.join(DESIGNS, "phase188_boot_proof.js"),
     os.path.join(ROOT, "code/webapp/app.js")],
    capture_output=True, text=True, timeout=30)
assert r.returncode == 0, r.stdout + r.stderr
assert "EVAL_OK" in r.stdout, r.stdout
assert "RETRY" in r.stdout, r.stdout
assert "EVAL_THROW" not in r.stdout, r.stdout
print("boot guard OK (no-Telegram boot reaches entry screen + RETRY)")
# Keepalive: 60s covers the 30-50s cold-start wake; schedule (10m)
# and the silent-to-the-user rule are unchanged.
assert "-m 60" in CRON and "-m 25" not in CRON, "keepalive timeout not 60s"
assert "every: 10m" in CRON, "keepalive schedule changed"
assert "Never send the user a message" in CRON, "keepalive silent rule gone"
print("keepalive 60s OK (schedule + silent rule unchanged)")

# --- 3. Job 2: Help & Support page ------------------------------------
groups = re.findall(r'settingsGroupEl\("([A-Z]+)"', JS)
assert groups == ["ACCOUNT", "PREFERENCES", "SUPPORT"], groups
rows = re.findall(r'settingsHubRow\("[^"]*", "([^"]+)"', JS)
assert rows == ["Profile", "Portfolio", "Privacy", "Payout wallet", "My QR",
                "From your profile", "Theme", "Notifications",
                "Data Control", "Help & Support", "About"], rows
assert rows.index("Help & Support") < rows.index("About"), \
    "Help row must sit above About in SUPPORT"
assert "details.help" in JS, "Help section not registered in the hub"
for q in ("How do I post a photo or video?",
          "How do I earn points?",
          "How do I unlock monetisation?",
          "What is a qualified referral?",
          "How do Stars tips work?",
          "How do Blood donors work?",
          "What is Skill Swap?",
          "Can I send voice messages?",
          "What is Nexa?",
          "How do I stay safe?"):
    assert q in JS, ("FAQ question missing:", q)
for fact in ("10 points", "check-in 20", "500 followers",
             "12 qualified referrals", "5000 lifetime points",
             "30-day check-in streak", "120 seconds", "5 MB",
             "TON, Gram or USDT", "10, 50, 100 or 250"):
    assert fact in JS, ("FAQ fact missing:", fact)
# No invented contact details anywhere in the Help block.
help_block = JS[JS.index("Help & Support"):JS.index("details.help")]
for bad in ("mailto:", "tel:", "http"):
    assert bad not in help_block, ("contact detail crept in:", bad)
# Actions: Ask Nexa opens the assistant; Report a problem opens a DM
# to Nexora Social (id 1, OFFICIAL_ID).
assert "Ask Nexa" in JS and 'showView("assistant")' in JS
assert "Report a problem" in JS and "openChat(1)" in JS
print("Help page OK (10 FAQs, real facts, no contact details, 2 actions)")
# Behavioural: the Report-a-problem route (DM to official id 1) works.
r = c.post("/messages/1",
           json={"text": "Help test: the app looks broken on my phone"},
           headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/messages/1", headers=ALICE)
assert r.status_code == 200, r.text
assert "Help test: the app looks broken" in r.text, r.text
print("Report-a-problem route OK (DM to Nexora Social id 1)")

# --- 4. Job 3: Settings moved from Me to the sidebar ------------------
assert "profile-settings-btn" not in JS, "Me Settings button still present"
assert 'data-go="settings"' in HTML, "sidebar Settings entry gone"
# Sidebar ACCOUNT order: My Profile, then Settings, then My QR.
assert (HTML.index('data-go="profile"')
        < HTML.index('data-go="settings"')
        < HTML.index('data-go="qr"')), "sidebar Settings misplaced"
# Me keeps name/photo/bio/cover/posts; the profile view still works.
assert "view-profile" in HTML and "openProfile(" in JS
assert 'if (name === "settings") loadSettings();' in JS
assert "  settings: [" in JS, "mascot settings-view tips gone"
print("sidebar move OK (Me button gone, sidebar entry in ACCOUNT)")

# --- 5. Version + routes + backup pins -------------------------------
assert HTML.count("?v=202") == 10, HTML.count("?v=202")
assert "?v=18" + "9" not in HTML
assert "app.js?v=202" in HTML and "games.js?v=202" in HTML
assert 'menu_url.rstrip("/") + "/?v=202"' in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 193, len(paths)
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
with TestClient(app) as cx:
    r = cx.get("/admin/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["version"] == 202, h["version"]
print("version ?v=202 + routes 183 + backup 52 OK")
print("PHASE 188 OK")
