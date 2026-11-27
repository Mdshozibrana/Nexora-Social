"""Phase 187 tests: Settings hub in the designcharan pattern.

The Settings page is a hub, not one long stack: a profile card on
top (avatar, name, @username, Edit), then ACCOUNT / PREFERENCES /
SUPPORT grouped cards of icon + label + chevron rows; a row tap
opens that section as a detail inside the same Settings view
(‹ Settings goes back). Every one of the 8 existing sections is
built exactly as before — Profile, Theme, Privacy, Notifications,
Data Control (+ After Rain), Payout wallet, From your profile,
My QR — nothing removed, nothing added. The About row is
information only (live build version, read off the app.js script
tag). Explicitly excluded by the owner's order: Language (never
ordered), a Dark Mode toggle (Nexora has 33 theme shades — the
Theme row instead) and Log Out (a Telegram Mini App has no
logout). Colours follow the member's theme (CSS vars), not the
screenshot's light palette.
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
os.environ["DATABASE_URL"] = "sqlite:///test_phase187.db"
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


ALICE = H(1871, "Alice", "alice187")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()

c = TestClient(app)

# --- 1. JS parses (node) — the refactor touched loadSettings, so a
# syntax slip would kill the whole shell, not just Settings.
for f in ("webapp/app.js", "webapp/games.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True,
                       cwd=os.path.join(ROOT, "code"))
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (app.js + games.js parse)")

# --- 2. Hub structure: groups in order, rows in order --------------
groups = re.findall(r'settingsGroupEl\("([A-Z]+)"', JS)
assert groups == ["ACCOUNT", "PREFERENCES", "SUPPORT"], groups
rows = re.findall(r'settingsHubRow\("[^"]*", "([^"]+)"', JS)
assert rows == ["Profile", "Privacy", "Payout wallet", "My QR",
                "From your profile", "Theme", "Notifications",
                "Data Control", "Help & Support", "About"], rows
print("hub groups + rows OK (3 groups, 10 rows, in order)")

# --- 3. All 8 existing sections still built inside loadSettings -----
for bit in ('sec("👤 Profile")', 'sec("🔒 Privacy")',
            'sec("🔔 Notifications")', 'sec("💰 Payout wallet")',
            'sec("📦 From your profile")', 'sec("🔳 My QR")',
            "themeCard()", "dataCard()", "rainCard()",
            "await myExtras()", 'loadMyQrInto("settings-qr-box")',
            "loadMySkills()"):
    assert bit in JS, ("section builder gone:", bit)
# ... and each is registered under a hub key (built, then moved —
# DOM moves keep listeners and input state).
for key in ("profile", "privacy", "notif", "wallet", "extras", "qr",
            "theme", "data", "help", "about"):
    assert 'reg("%s"' % key in JS or 'details.%s' % key in JS, key
print("all 8 sections still built + registered OK")

# --- 4. Exclusions: no Language row, no Dark Mode toggle, no Log Out
assert "Dark Mode" not in JS, "Dark Mode toggle crept in"
assert "Log Out" not in JS, "Log Out button crept in"
assert "Language" not in rows, "Language row crept in"
# The hub opens details; it never navigates away or logs out.
assert "openSettingsDetail" in JS and "renderSettingsHub" in JS
assert "settingsDetailKey" in JS
assert "‹ Settings" in JS, "detail back button missing"
assert "else if (settingsDetailKey) renderSettingsHub();" in JS, \
    "Telegram back button does not close a Settings detail"
print("exclusions OK (no Language / Dark Mode / Log Out)")

# --- 5. Profile card + About version ----------------------------------
for bit in ("settings-profile-card", "settings-profile-name",
            "settings-profile-sub", "✎ Edit", "avatarEl(",
            "u.photo_file_id", "u.username"):
    assert bit in JS, ("profile card bit gone:", bit)
assert "function settingsVersion()" in JS
assert 'script[src*="app.js?v="]' in JS, \
    "version is not read off the live script tag"
assert '"v" + ver' in JS, "About pill does not show v<build>"
assert "Version v" in JS and "build ?v=" in JS
for cls in ("settings-profile-card", "settings-edit",
            "settings-group-label", "settings-group",
            "settings-row-btn", "settings-row-ic",
            "settings-row-label", "settings-row-sub",
            "settings-row-value", "settings-ver-pill",
            "settings-row-chev", "settings-back",
            "settings-detail-body", "settings-about-name"):
    assert ("." + cls) in CSS, ("CSS class gone:", cls)
# Notifications keeps the pattern's two-line row, with a truthful
# Nexora subtitle (no email notifications exist here).
assert '"In-app & Telegram bot"' in JS
print("profile card + About version + CSS OK")

# --- 6. Behavioural: the hub's data sources are intact -------------
# The profile card reads /users/{id} (name, @username, photo,
# private flag); the sections read notification prefs, wallet,
# blocked and muted lists.
r = c.get("/me/notification-prefs", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/users/1871", headers=ALICE)
assert r.status_code == 200, r.text
u = r.json()
for field in ("first_name", "username", "photo_file_id", "is_private"):
    assert field in u, field
assert u["first_name"] == "Alice" and u["username"] == "alice187"
r = c.post("/me/notification-prefs",
           json={"likes": False, "comments": True}, headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/notification-prefs", headers=ALICE)
assert r.json()["prefs"]["likes"] is False, r.json()
assert r.json()["prefs"]["comments"] is True, r.json()
r = c.get("/me/wallet", headers=ALICE)
assert r.status_code == 200, r.text
r = c.post("/me/wallet", json={"network": "TON", "address": "EQabc"},
           headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/wallet", headers=ALICE)
assert r.json()["wallet_address"] == "EQabc", r.json()
for path in ("/me/blocked", "/me/muted"):
    r = c.get(path, headers=ALICE)
    assert r.status_code == 200, (path, r.text)
print("hub data sources OK (profile, notif prefs, wallet, lists)")

# --- 7. Version + routes + backup pins -------------------------------
assert HTML.count("?v=195") == 10, HTML.count("?v=195")
assert "?v=18" + "9" not in HTML
assert "app.js?v=195" in HTML and "games.js?v=195" in HTML
assert 'menu_url.rstrip("/") + "/?v=195"' in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 184, len(paths)
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
with TestClient(app) as cx:
    r = cx.get("/admin/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["version"] == 195, h["version"]
print("version ?v=195 + routes 183 + backup 52 OK")
print("PHASE 187 OK")
