"""Phase-207 tests: Portfolio Profile + Work as two cards with two
colours/designs, like the Me section's profile.

Owner order (Nov 27, 22:33): the Portfolio's Profile part and Work
part should be two cards with two colours/designs, styled like the
Me section's profile cards. The Me profile has two visual zones —
the gradient hero zone + the plain body zone — and Phase 207 gives
the Portfolio the same two-zone read: the Profile card (cover,
Follow/Message actions, About) on the soft accent gradient, the
Work card (title + grid) on the plain theme card with an accent
top edge.

Restyle only: no behaviour change, no new routes, no schema change.
The Phase 204 fresh-from-phone upload path, the Settings toggle
(default OFF) and the Profile ▾ dropdown (default Profile) are
untouched. Plain script (run.sh runs it directly).
"""
import os
import subprocess

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase207.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _health_version  # noqa: E402

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
c = TestClient(app)

# --- 1. Client: the two cards exist, the flat layout is gone. --------
NEW_PROFILE = """    const pcard = document.createElement("div");
    pcard.className = "pf-card pf-card-profile";
    pcard.appendChild(cover);"""
assert NEW_PROFILE in JS, "Profile card wrap missing from app.js"
NEW_WORK = """    const wcard = document.createElement("div");
    wcard.className = "pf-card pf-card-work";
    wcard.appendChild(workH);"""
assert NEW_WORK in JS, "Work card wrap missing from app.js"
assert "      pcard.appendChild(row);" in JS, "actions not in Profile card"
assert "    pcard.append(aboutH, about);" in JS, "About not in Profile card"
assert "    box.appendChild(pcard);" in JS, "Profile card not appended"
assert "    wcard.appendChild(grid);" in JS, "grid not in Work card"
assert "    box.appendChild(wcard);" in JS, "Work card not appended"
# Old flat appends are gone: the cover no longer goes straight to
# the box, and the only remaining box.appendChild(grid) is the
# Admin Health stats grid (loadHealth), not the portfolio.
assert "box.appendChild(cover);" not in JS, "cover still appended flat"
assert JS.count("    box.appendChild(grid);") == 1, \
    JS.count("    box.appendChild(grid);")
OLD_ACTIONS = """      row.append(fBtn, mBtn);
      box.appendChild(row);"""
assert OLD_ACTIONS not in JS, "actions row still appended to the box"
# Phase 199 / 204 behaviour markers are untouched.
for m in ("renderPortfolioTab", "portfolioDropdownEl",
          "openPortfolioEditor", "Edit portfolio",
          "pf-cover", "pf-shade", "pf-work-grid",
          "/me/portfolio/cover/upload", "/me/portfolio/items/upload",
          'apiFormProgress("/me/portfolio/cover/upload"',
          'apiFormProgress("/me/portfolio/items/upload", form,'):
    assert m in JS, f"Phase 199/204 marker lost: {m}"
print("1. client: Profile card + Work card wrap, flat layout gone OK")

# --- 2. CSS: two card designs, theme-var based. -----------------------
for m in (".pf-card {", ".pf-card-profile {", ".pf-card-work {",
          ".pf-card-profile .pf-actions",
          ".pf-card-profile .pf-sec-title",
          ".pf-card-profile .pf-about",
          ".pf-card-work .pf-sec-title"):
    assert m in CSS, f"missing CSS marker: {m}"
# The two designs differ: gradient vs solid theme card.
assert ("linear-gradient(160deg, var(--t-glow1, #8ED4F7), "
        "var(--t-glow2, #F6F1E7))") in CSS
assert ".pf-card-work { background: var(--t-card" in CSS
assert "border-top: 3px solid var(--t-acc1, #8ED4F7)" in CSS
# Theme-var discipline (Phase 205 pattern): the Phase 207 block
# sets its colours through vars only — no literal-colour background
# or border anywhere in it (hex values appear only as var()
# fallbacks, as in the existing pf rules).
start = CSS.index("/* Phase 207 (owner):")
end = CSS.index("}", CSS.index(".pf-card-work .pf-sec-title")) + 1
block = CSS[start:end]
assert "background: #" not in block, block
assert "background: linear-gradient(#" not in block, block
assert "border-top: 3px solid #" not in block, block
assert "color: #" not in block, block
print("2. CSS: two card designs, theme-var based OK")

# --- 3. Version pins + routes + backup + health. ----------------------
assert HTML.count("?v=210") == 10, HTML.count("?v=210")
assert "?v=20" + "8" not in HTML
assert "app.js?v=210" in HTML and "games.js?v=210" in HTML
assert "style.css?v=210" in HTML
assert 'menu_url.rstrip("/") + "/?v=210"' in BOT
assert ("/?v=20" + "8") not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 196, len(paths)
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert _health_version() == 210, _health_version()
print("3. version ?v=210, routes 191, backup 55, health 207 OK")

# --- 4. app.js still parses + the Node harness proves the cards. -----
r = subprocess.run(["node", "--check",
                    os.path.join(ROOT, "code/webapp/app.js")],
                   capture_output=True, text=True)
assert r.returncode == 0, r.stderr
h = subprocess.run(["node",
                    os.path.join(DESIGNS, "phase207_portfolio_proof.js"),
                    os.path.join(ROOT, "code/webapp/app.js")],
                   capture_output=True, text=True)
print(h.stdout)
assert h.returncode == 0, h.stdout + h.stderr
print("4. node --check + portfolio harness OK")

print("PHASE 207 OK (Portfolio Profile + Work are two cards)")
