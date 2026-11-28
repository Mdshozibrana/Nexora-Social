"""Phase-201 tests — CONVERTED by Phase 203 (owner order Nov 28, 2026:
"Museum রিমুভ করে দিও। পছন্দ হয়নি আর অ্যাপস বড় হয়ে যাচ্ছে").
Phase 201 built a NEW 3D-walkthrough Museum (Nov 27, 2026); Phase 203
removes it entirely, following the Phase 152 / Phase 161 removal
pattern: this suite proves Museum is gone instead of being deleted.
Gone: sidebar entry, profile button, the whole client 3D block
(openMuseum / buildMuseumScene / muFurniture / mu-* ids + classes),
the 4 routes, the _museum_* helpers, the _media_visible museum
branch, the Nexa MUSEUM paragraph, the "museum" rate bucket.
RETAINED on purpose (Phase 169 precedent): the museum_items table +
model + backup-list entry + RLS DML grant — _restore_backup rejects
backups with unknown tables, so removing it would make every backup
taken since ?v=201 unrestorable. The table holds no live meaning
anymore; its rows are orphaned data.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase201.db"
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
from app.config import settings, RATE_LIMITS  # noqa: E402

def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(2011, "Alice", "alice")
BOB = H(2012, "Bob", "bob")
CAROL = H(2013, "Carol", "carol")
DAVE = H(2014, "Dave", "dave")
OFFICIAL = H(1, "Nexora Social", "nexora")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
MAIN = open(os.path.join(ROOT, "code/app/main.py")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()

c = TestClient(app)

# --- 1. Client: no museum anywhere. --------------------------------------
assert "museum" not in HTML.lower(), "museum in index.html"
assert "museum" not in JS.lower(), "museum in app.js"
assert "museum" not in CSS.lower(), "museum in style.css"
assert "museum" not in BOT.lower(), "museum in bot.py"
assert '<section id="view-museum"' not in HTML
assert 'data-go="museum"' not in HTML
assert '"nearby", "qr", "trending", "settings", "blood", "skills"]' in JS
assert '"settings", "blood", "skills"].forEach(v => {' in JS
for bit in ("openMuseum", "reloadMuseum", "loadMuseum",
            "buildMuseumScene", "stopMuseum", "closeMuseumSheet",
            "openMuseumSheet", "museumSaveItem", "museumRemoveItem",
            "museumFrameTap", "museumFloorTap", "museumPickPhoto",
            "muHas3D", "MUSEUM_ROOMS", "MUSEUM_FURNITURE",
            "MUSEUM_WALL_SLOTS", "MUSEUM_FLOOR_SLOTS",
            "MUSEUM_THEMES", "museumZoom",
            "mu-owner", "mu-room-tabs", "mu-stage", "mu-canvas",
            "mu-chips", "mu-fallback", "mu-sheet", "mu-prev",
            "mu-next", "mu-status", "mu-nogl", "mu-room-name",
            "mu-tab", "mu-chip", "mu-fb-card", "mu-cat-row",
            ".mu-stage", ".mu-tab", ".mu-chip"):
    assert bit not in JS, bit
    assert bit not in CSS, bit
    assert bit not in HTML, bit
# The app got smaller: the 3D museum block is gone.
assert len(JS) < 517614, len(JS)
print("1. client museum-free + app.js smaller OK")

# --- 2. Server: no museum routes, helpers, or text. ----------------------
assert "_museum_visible_to" not in MAIN
assert "_museum_item_dict" not in MAIN
assert "_museum_out" not in MAIN
assert "MuseumItemIn" not in MAIN
assert "MUSEUM_ROOMS" not in MAIN
assert "MUSEUM_FURNITURE" not in MAIN
assert "MUSEUM_SLOTS" not in MAIN
assert '"museum"' not in MAIN, "museum string left in main.py"
assert "MUSEUM:" not in MAIN, "Nexa MUSEUM paragraph left"
assert "/museum" not in MAIN
assert "museum" not in RATE_LIMITS, RATE_LIMITS
paths = {rt.path for rt in app.routes}
assert len(paths) == 191, len(paths)
assert not any("museum" in p for p in paths), paths
r = c.get("/me/museum", headers=ALICE)
assert r.status_code == 404, r.text
r = c.post("/me/museum/items",
           json={"room": "entrance", "kind": "photo", "slot": 0},
           headers=ALICE)
assert r.status_code == 404, r.text
r = c.get("/users/2011/museum", headers=ALICE)
assert r.status_code == 404, r.text
print("2. server museum-free + routes 189 OK")

# --- 3. Retention: table + model + backup + grants stay. ------------------
# Phase 169 precedent: museum_items stays so backups taken since
# ?v=201 still restore (_restore_backup rejects unknown tables).
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert ("museum_items", models.MuseumItem) in _BACKUP_TABLES
ROLE = open(os.path.join(
    ROOT, "code/migrations/phase164_rls_role.sql")).read()
assert "museum_items" in ROLE, "RLS role script lacks museum_items"
RLS = open(os.path.join(
    ROOT, "code/migrations/phase164_rls.sql")).read()
assert "museum_items" not in RLS
print("3. museum_items retained (backup compat) OK")

# --- 4. Version. ----------------------------------------------------------
assert HTML.count("?v=207") == 10, HTML.count("?v=207")
assert "?v=20" + "3" not in HTML
assert "app.js?v=207" in HTML and "games.js?v=207" in HTML
assert 'menu_url.rstrip("/") + "/?v=207"' in BOT
assert ("/?v=20" + "2") not in BOT
print("4. version ?v=207 OK")

# --- 5. app.js still parses. ----------------------------------------------
r = subprocess.run(["node", "--check",
                    os.path.join(ROOT, "code/webapp/app.js")],
                   capture_output=True, text=True)
assert r.returncode == 0, r.stderr
print("5. node --check OK")

print("PHASE 201 REMOVAL GUARD OK (Museum gone, neighbours intact)")
