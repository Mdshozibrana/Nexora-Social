"""Phase-208 tests: the whole Games section is dark green — the
games list AND the in-game views — while the games stay readable
and the buttons usable.

Owner order (Nov 27, 23:01): "গেমস সেকশনের পুরো কালার ডার্ক
গ্রীন করে দাও" — the whole Games section dark green, list +
in-game views. The palette lives in --gx-* vars scoped to
#view-games / #view-game, so nothing outside the Games section is
touched. The five flat 2D canvases (Tetris, Breakout, Pong, Space
Invaders, Pac-Man) share one very-dark-green board colour
GX_CANVAS_BG; Snake keeps its Nokia-LCD green, Archery keeps its
theme gradient sky and Flappy keeps its sky — those colours ARE
the games' look. Phase 197's vivid buttons (GAS green / BRAKE red
/ steer blue-teal) and Phase 198's SVG mini-scene icons are
untouched, as are the full-screen game view and the HUD layout.

Restyle only: no behaviour change, no new routes, no schema
change. Plain script (run.sh runs it directly).
"""
import os
import subprocess

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase208.db"
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
GAMES = open(os.path.join(ROOT, "code/webapp/games.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
c = TestClient(app)

# --- 1. games.js: one shared dark-green board, old fills gone. -------
assert 'const GX_CANVAS_BG = "#0C2115";' in GAMES, "GX const missing"
assert GAMES.count("ctx.fillStyle = GX_CANVAS_BG;") == 5, \
    GAMES.count("ctx.fillStyle = GX_CANVAS_BG;")
for old in ('"#14141f"', '"#101408"', '"#070714"', '"#0B1035"',
            '"rgba(7,7,20,.85)"'):
    assert old not in GAMES, f"old fill still present: {old}"
# The game-over overlays were retinted to the same dark green.
assert GAMES.count('ctx.fillStyle = "rgba(12,33,21,.85)";') == 2, \
    GAMES.count('ctx.fillStyle = "rgba(12,33,21,.85)";')
# Kept palettes: Snake's Nokia-LCD green, Flappy's sky.
assert GAMES.count('"#b7c25e"') == 1, GAMES.count('"#b7c25e"')
assert GAMES.count('"#8ED6F2"') == 1, GAMES.count('"#8ED6F2"')
# All 13 games still registered; 197 buttons + 198 icons wired.
assert GAMES.count("registerGame({") == 13, GAMES.count("registerGame({")
for m in ("fd-gas", "fd-brake", "fd-left", "fd-right", "rr-steer",
          "g-icon", "game-card"):
    assert m in GAMES, f"Phase 197/198 marker lost: {m}"
print("1. games.js: GX board x5, old fills gone, kept palettes OK")

# --- 2. CSS: dark-green room, theme-var based, buttons/icons kept. ---
assert "Phase 208 — Games section dark green" in CSS, "block missing"
assert "#view-games, #view-game {" in CSS, "gx var scope missing"
for m in ("--gx-bg: #0B2E1F;", "--gx-bg2: #0F3D29;",
          "--gx-ink: #EAF7EE;", "--gx-amber: #FDE68A;",
          "#view-games { background: var(--gx-bg);",
          "#view-games .game-card { background: var(--gx-bg2);",
          "#view-game { background: var(--gx-bg);",
          "#view-game #game-score { color: var(--gx-amber); }",
          ".fd-panel { background: rgba(6, 26, 17, .78); }",
          ".fd-speed { background: rgba(6, 26, 17, .72); }"):
    assert m in CSS, f"missing CSS marker: {m}"
# The full-screen immersive shell now opens on dark green.
assert "background: var(--gx-bg, #0B2E1F);" in CSS, \
    "immersive bg not dark green"
# Theme-var discipline (Phase 205/207 pattern): the Phase 208 block
# sets its colours through vars only — no literal-colour background,
# colour or border anywhere in it (hex values appear only as the
# --gx-* definitions themselves, as in the existing theme rules).
start = CSS.index("Phase 208 — Games section dark green")
end = CSS.index("}", CSS.index(
    ".fd-speed { background: rgba(6, 26, 17, .72)")) + 1
block = CSS[start:end]
assert "background: #" not in block, block
assert "background: linear-gradient(#" not in block, block
assert "color: #" not in block, block
assert "border: 1px solid #" not in block, block
assert "border-top: #" not in block, block
assert "box-shadow: #" not in block, block
# Phase 197's vivid buttons were NOT dulled, and the Phase 198
# icon size is untouched.
for m in ("#22C55E", "#EF4444", "#3B82F6", "#14B8A6"):
    assert m in CSS, f"Phase 197 button colour lost: {m}"
assert ".game-card .g-icon svg { width: 44px; height: 44px;" in CSS, \
    "Phase 198 icon size changed"
print("2. CSS: dark-green room, var discipline, buttons/icons kept OK")

# --- 3. Version pins + routes + backup + health. ----------------------
assert HTML.count("?v=208") == 10, HTML.count("?v=208")
assert "?v=20" + "7" not in HTML
assert "app.js?v=208" in HTML and "games.js?v=208" in HTML
assert "style.css?v=208" in HTML
assert 'menu_url.rstrip("/") + "/?v=208"' in BOT
assert ("/?v=20" + "7") not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 191, len(paths)
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert _health_version() == 208, _health_version()
print("3. version ?v=208, routes 191, backup 55, health 208 OK")

# --- 4. JS still parses + the Node harness proves the dark green. ----
for name in ("app.js", "games.js"):
    r = subprocess.run(["node", "--check",
                        os.path.join(ROOT, "code/webapp", name)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
h = subprocess.run(["node",
                    os.path.join(DESIGNS, "phase208_games_proof.js"),
                    os.path.join(ROOT, "code/webapp/games.js")],
                   capture_output=True, text=True)
print(h.stdout)
assert h.returncode == 0, h.stdout + h.stderr
print("4. node --check + games harness OK")

print("PHASE 208 OK (Games section dark green)")
