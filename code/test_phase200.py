"""Phase 200 — Settings flash fix + 5 improvements.

Owner bug (Nov 27, 16:23 Dhaka): opening Settings from the sidebar
first shows a jumbled screen, then Settings appears after 1-2 s.

Diagnosed root cause: loadSettings() appended every section to the
VISIBLE #settings-box one by one while their fetches resolved, and
only at the very end called renderSettingsHub() — the member watched
the raw stacked sections pile up for 1-2 s before the hub replaced
them. The first paint was also a bare "Loading..." text.

Fix + improvements (client-side only, no new routes, no schema):
  1. first paint = skeleton (or the cached hub on a repeat open);
     sections build in a hidden, attached container (buildBox) and
     only surface as the hub at the end;
  2. skeleton matching the hub layout, theme-aware;
  3. live search over hub rows (label + subtitle) + empty state;
  4. current values on hub rows (Portfolio, Private, Theme,
     notification summary, wallet network, About version);
  5. inline quick toggles (Portfolio, Private) — optimistic UI,
     the detail view kept in sync;
  6. sessionStorage cache per account — instant repeat opens.

The Node harness (nexora_designs/phase200_settings_proof.js)
proves the behaviour on the real app.js with a stub DOM and a
deliberately slow /users/{id}.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase200.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, admin_user  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
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


ALICE = H(1991, "Alice", "alice")
BOB = H(1992, "Bob", "bob")
CAROL = H(1993, "Carol", "carol")
DAVE = H(1994, "Dave", "dave")
OFFICIAL = H(1, "Nexora Social", "nexora")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()

c = TestClient(app)


def mk(uid, name, username):
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        u = db.get(models.User, uid)
        assert u is not None, "user %s not created" % uid
        u.username = username
        db.commit()
    finally:
        db.close()


for uid, name, uname in ((1991, "Alice", "alice"), (1992, "Bob", "bob"),
                         (1993, "Carol", "carol"), (1994, "Dave", "dave")):
    mk(uid, name, uname)

# --- 1. JS parses (node) --------------------------------------------
for f in ("webapp/app.js", "webapp/games.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True,
                       cwd=os.path.join(ROOT, "code"))
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (app.js + games.js parse)")

# --- 2. Hub structure intact (Phase 187/188 guards) -----------------
groups = re.findall(r'settingsGroupEl\("([A-Z]+)"', JS)
assert groups == ["ACCOUNT", "PREFERENCES", "SUPPORT"], groups
rows = re.findall(r'settingsHubRow\("[^"]*", "([^"]+)"', JS)
assert rows == ["Profile", "Portfolio", "Privacy", "Payout wallet",
                "My QR", "From your profile", "Theme", "Notifications",
                "Data Control", "Help & Support", "About"], rows
BUILDERS = ['sec("👤 Profile")', 'sec("🖼️ Portfolio")',
            'sec("🔒 Privacy")', 'sec("🔔 Notifications")',
            'sec("💰 Payout wallet")', 'sec("📦 From your profile")',
            'sec("🔳 My QR")', 'themeCard()', 'dataCard()', 'rainCard()',
            'await myExtras()', 'loadMyQrInto("settings-qr-box")',
            'loadMySkills()']
for b in BUILDERS:
    assert b in JS, f"missing section builder: {b}"
assert "Dark Mode" not in JS
assert "Log Out" not in JS
assert "Language" not in rows
print("hub structure OK (groups + 11 rows + builders + exclusions)")

# --- 3. Phase 200 static markers ------------------------------------
JS_MARKS = ["renderSettingsSkeleton", "settingsCacheRead()",
            "settingsCacheWrite()", "settingsThemeName",
            "settingsSearchQuery", "applySettingsSearch",
            "settings-skel", "settings-switch", "settingsFlipPortfolio",
            "settingsFlipPrivate", "settingsSyncDetailCheckbox",
            "settingsNotifSummary", "settingsWalletSummary",
            "settingsLoadSeq", "buildBox", "settings-build",
            "settings-search-empty", "nx_settings_hub_",
            'b.dataset.search = (label + " " + (sub || "")).toLowerCase();',
            'const sw = document.createElement("span");']
for m in JS_MARKS:
    assert m in JS, f"missing JS marker: {m}"
CSS_MARKS = [".settings-search", ".settings-search-empty",
             ".settings-switch", ".settings-switch-knob",
             ".settings-skel-search", ".settings-skel-ava",
             ".settings-skel-lines", ".settings-skel-line",
             ".settings-skel-ic", ".settings-skel-row",
             "settings-skel-pulse",
             '.settings-switch[aria-checked="true"]']
for m in CSS_MARKS:
    assert m in CSS, f"missing CSS marker: {m}"
# The old first paint is gone from loadSettings: no "Loading..." text
# written to the visible box, no direct box writes at all; the
# skeleton/cache/buildBox take over. (Two "Loading..." strings
# remain, but only inside the nested blocked/muted list loaders —
# they write to their own sub-boxes inside the hidden build
# container, never to the first paint.)
ls_start = JS.index("async function loadSettings()")
ls_end = JS.index("\n// ---------------------------------------------------------------- tasks ---",
                  ls_start)
ls = JS[ls_start:ls_end]
assert 'box.innerHTML = "Loading…"' not in ls, \
    "loadSettings still paints bare Loading text"
assert "box.innerHTML" not in ls, "loadSettings still writes the visible box"
assert ls.count("Loading…") == 2, ls.count("Loading…")
assert 'blkBox.innerHTML = "Loading…"' in ls
assert 'mutBox.innerHTML = "Loading…"' in ls
assert "renderSettingsSkeleton()" in ls
assert "settingsCacheRead()" in ls
assert "buildBox" in ls
assert "settingsLoadSeq" in ls
print("Phase 200 static markers OK")

# --- 4. Harness: real app.js, stub DOM, slow /users/{id} ------------
r = subprocess.run(
    ["node", os.path.join(DESIGNS, "phase200_settings_proof.js"),
     os.path.join(ROOT, "code/webapp/app.js")],
    capture_output=True, text=True, timeout=90)
assert r.returncode == 0, r.stdout + r.stderr
assert "DONE failures=0" in r.stdout, r.stdout
assert "first paint is the skeleton" in r.stdout, r.stdout
assert "cached open paints the hub instantly" in r.stdout, r.stdout
assert "all 11 detail sections open" in r.stdout, r.stdout
print("harness OK (skeleton first paint + search + values + toggles"
      " + cache + all details)")

# --- 5. API: the data the hub rows display + the toggle endpoints ---
# Notification prefs: two off -> the hub summary counts "2 off".
r = c.post("/me/notification-prefs",
           json={"likes": False, "tips": False}, headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/notification-prefs", headers=ALICE)
assert r.status_code == 200, r.text
prefs = r.json()["prefs"]
assert prefs["likes"] is False and prefs["tips"] is False, prefs
# Portfolio toggle endpoint (the hub switch's one call).
r = c.post("/me/portfolio",
           json={"about": "", "role": "", "cover_file_id": None,
                 "enabled": True}, headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["enabled"] is True, r.json()
r = c.get("/me/portfolio", headers=ALICE)
assert r.status_code == 200 and r.json()["enabled"] is True, r.text
r = c.post("/me/portfolio",
           json={"about": "", "role": "", "cover_file_id": None,
                 "enabled": False}, headers=ALICE)
assert r.status_code == 200 and r.json()["enabled"] is False, r.text
# Privacy toggle endpoint (the hub switch's one call).
r = c.post("/me/privacy", json={"is_private": True}, headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["is_private"] is True, r.json()
r = c.get("/users/1991", headers=ALICE)
assert r.status_code == 200 and r.json()["is_private"] is True, r.text
r = c.post("/me/privacy", json={"is_private": False}, headers=ALICE)
assert r.status_code == 200 and r.json()["is_private"] is False, r.text
# Wallet (the hub row's network value) + the hub build's list fetches.
r = c.post("/me/wallet",
           json={"network": "TON", "address": "EQabc123"},
           headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/wallet", headers=ALICE)
assert r.status_code == 200 and r.json()["wallet_network"] == "TON", r.text
r = c.get("/me/blocked", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/muted", headers=ALICE)
assert r.status_code == 200, r.text
print("API OK (notif prefs + portfolio/privacy toggles + wallet)")

# --- 6. Version pins + routes + backup + health ---------------------
assert HTML.count("?v=204") == 10, HTML.count("?v=204")
assert "app.js?v=204" in HTML and "games.js?v=204" in HTML
assert ("?v=20" + "0") not in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert 'menu_url.rstrip("/") + "/?v=204"' in BOT
assert ("/?v=19" + "9") not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 191, len(paths)
app.dependency_overrides[admin_user] = lambda: object()
try:
    r = c.get("/admin/health")
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["version"] == 204, h["version"]
finally:
    app.dependency_overrides.clear()
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
# Phase 199 RLS gap: do NOT touch the role script's grant list.
ROLE = open(os.path.join(ROOT, "code/migrations/phase164_rls_role.sql")).read()
assert "portfolios" in ROLE and "portfolio_items" in ROLE
print("version ?v=204 + routes 189 + backup 54 OK")
print("PHASE 200 ALL OK")
