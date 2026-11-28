"""Phase 205 — Settings inner detail pages restyled like current
social-media apps (owner order Nov 27, 22:33).

The hub was modernised in Phase 187 and its loading fixed in
Phase 200; the DETAIL pages still wore the old simple look — a
bare "‹ Settings" text link, a plain card title, raw inputs, small
grey buttons, flat rows. Restyle only: no behaviour change, no new
routes, no schema change.

  * detail top bar: back pill ("‹ Settings", exact label kept) +
    large title from a static map;
  * notification rows split into label + description lines;
  * Help FAQ questions/answers get row classes;
  * About version renders as a pill;
  * wallet Save is a primary (wide) action;
  * the restyle is CSS scoped under .settings-detail (Me / profile
    pages that reuse themeCard/dataCard/rainCard/myExtras keep
    their own look) and theme-var based (no hard-coded palette),
    so it works in light and dark themes.

Proof: the Phase 205 Node harness (real app.js, stub DOM, derived
from the Phase 200 harness — 56 checks) + the Phase 200 harness
itself, still green — skeleton, search, values, toggles, cache,
all 11 details.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase205.db"
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


ALICE = H(2051, "Alice", "alice")

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


mk(2051, "Alice", "alice")

# --- 1. JS parses (node) --------------------------------------------
for f in ("webapp/app.js", "webapp/games.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True,
                       cwd=os.path.join(ROOT, "code"))
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (app.js + games.js parse)")

# --- 2. New JS markers ----------------------------------------------
NEW_JS = ["SETTINGS_DETAIL_TITLES", "settings-detail-head",
          "settings-detail-title",
          "SETTINGS_DETAIL_TITLES[key] || \"Settings\"",
          "settings-notif-tx", "settings-notif-label",
          "settings-notif-desc",
          "settings-faq-q", "settings-faq-a",
          'aboutVer.className = "hint settings-ver-pill"',
          'walSave.className = "wide"']
for m in NEW_JS:
    assert m in JS, f"missing new JS marker: {m}"
# The title map covers all 11 detail keys, with the hub's labels.
for key, title in (("profile", "👤 Profile"),
                   ("portfolio", "🖼️ Portfolio"),
                   ("privacy", "🔒 Privacy"),
                   ("wallet", "💰 Payout wallet"),
                   ("qr", "🔳 My QR"),
                   ("extras", "📦 From your profile"),
                   ("theme", "🎨 Theme"),
                   ("notif", "🔔 Notifications"),
                   ("data", "🗂️ Data Control"),
                   ("help", "❓ Help & Support"),
                   ("about", "ℹ️ About")):
    assert f'{key}: "{title}"' in JS, f"title map missing {key}"
print("new JS markers OK (header + titles + notif/faq/about/wallet)")

# --- 3. Preserved behaviour pins (nothing removed) -------------------
BUILDERS = ['sec("👤 Profile")', 'sec("🖼️ Portfolio")',
            'sec("🔒 Privacy")', 'sec("🔔 Notifications")',
            'sec("💰 Payout wallet")', 'sec("📦 From your profile")',
            'sec("🔳 My QR")', 'themeCard()', 'dataCard()', 'rainCard()',
            'await myExtras()', 'loadMyQrInto("settings-qr-box")',
            'loadMySkills()']
for b in BUILDERS:
    assert b in JS, f"missing section builder: {b}"
assert "‹ Settings" in JS, "detail back label gone"
assert "else if (settingsDetailKey) renderSettingsHub();" in JS
assert "dataWrap.append(dataCard(), rainCard())" in JS
assert "Monetization card below" in JS
assert "settings-wallet-save" in JS
assert "notif-row-" in JS and "loadBlocked" in JS
assert JS.count("🔒 Private account — only approved followers will see your posts.") == 1
assert "Dark Mode" not in JS and "Log Out" not in JS
# The old single-line notif text is gone; the label/desc split
# replaced it (the em-dash join no longer exists in the builder).
assert 'label + " — " + desc' not in JS
# Phase 200 behaviour markers intact.
for m in ("renderSettingsSkeleton", "settingsCacheRead()",
          "settingsCacheWrite()", "settingsSearchQuery",
          "applySettingsSearch", "settings-switch",
          "settingsFlipPortfolio", "settingsFlipPrivate",
          "settingsSyncDetailCheckbox", "settingsLoadSeq", "buildBox"):
    assert m in JS, f"missing Phase 200 marker: {m}"
print("preserved behaviour pins OK (builders + back + Phase 200)")

# --- 4. CSS markers: new restyle + pinned old classes ---------------
NEW_CSS = [".settings-detail-head", ".settings-detail-title",
           ".settings-detail {",
           ".settings-sec > .settings-head:first-child",
           ".settings-detail .settings-sec",
           ".settings-detail .settings-sub",
           ".settings-detail .hint",
           '.settings-detail input:not([type="checkbox"])',
           ".settings-detail button.wide",
           ".settings-detail button.btn",
           ".settings-detail .privacy-row",
           ".settings-notif-tx", ".settings-notif-label",
           ".settings-notif-desc",
           ".settings-detail .settings-blocked",
           ".settings-detail .settings-blocked-row",
           ".settings-detail .settings-skill-row",
           ".settings-detail .settings-faq-q",
           ".settings-detail .settings-faq-a",
           ".settings-detail .settings-ver-pill",
           ".settings-detail .theme-card",
           ".settings-detail .data-card:not(.rain-card)"]
for m in NEW_CSS:
    assert m in CSS, f"missing new CSS marker: {m}"
# Pinned by test_phase144 / 187 / 200 — the classes still exist.
for m in ("settings-sec", "settings-head", "settings-sub",
          "settings-row", "settings-blocked-row", "settings-back",
          "settings-detail-body", "settings-about-name",
          "settings-ver-pill", "settings-search", ".settings-switch",
          ".settings-switch-knob", ".settings-skel-row",
          "settings-skel-pulse", "privacy-row"):
    assert m in CSS, f"missing pinned CSS marker: {m}"
print("CSS markers OK (new restyle + pinned old classes)")

# --- 5. Theme-var guard: the Phase 205 block carries no hard-coded
# colours — every colour comes from a theme var (var() fallbacks
# may name a colour, but no colour may sit outside a var()).
start = CSS.index("Phase 205: Settings detail pages restyled")
block = CSS[start:]
block = block[:block.index("/* Phase 151:")]
stripped = re.sub(r"var\([^)]*\)", "VAR", block)
assert not re.search(r"#[0-9a-fA-F]{3,8}\b", stripped), \
    "hard-coded hex colour in the Phase 205 block"
assert not re.search(r"rgba?\(", stripped), \
    "hard-coded rgb()/rgba() colour in the Phase 205 block"
assert block.count("var(--") >= 20, block.count("var(--")
print("theme-var guard OK (Phase 205 block is var-only)")

# --- 6. Node harnesses: Phase 205 + Phase 200, both green -----------
for harness, want in (("phase205_settings_proof.js", "56"),
                      ("phase200_settings_proof.js", None)):
    r = subprocess.run(
        ["node", os.path.join(DESIGNS, harness),
         os.path.join(ROOT, "code/webapp/app.js")],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DONE failures=0" in r.stdout, r.stdout
    if want:
        passes = len(re.findall(r"^PASS ", r.stdout, re.M))
        assert passes == int(want), (harness, passes, r.stdout)
        assert "all 11 detail sections open with modern header" in r.stdout
        assert "notif rows are two-line (label + desc)" in r.stdout
    else:
        assert "all 11 detail sections open" in r.stdout
    print(f"harness OK ({harness})")

# --- 7. API smoke: the settings endpoints are untouched --------------
r = c.get("/me/notification-prefs", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/wallet", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/blocked", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/muted", headers=ALICE)
assert r.status_code == 200, r.text
print("API smoke OK (notif prefs + wallet + blocked/muted)")

# --- 8. Version pins + routes + backup + health ---------------------
assert HTML.count("?v=205") == 10, HTML.count("?v=205")
assert "app.js?v=205" in HTML and "games.js?v=205" in HTML
assert ("?v=20" + "4") not in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert 'menu_url.rstrip("/") + "/?v=205"' in BOT
assert ("/?v=20" + "4") not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 191, len(paths)
app.dependency_overrides[admin_user] = lambda: object()
try:
    r = c.get("/admin/health")
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["version"] == 205, h["version"]
finally:
    app.dependency_overrides.clear()
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
print("version ?v=205 + routes 191 + backup 55 OK")
print("PHASE 205 ALL OK")
