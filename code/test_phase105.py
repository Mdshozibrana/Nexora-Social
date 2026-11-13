"""Phase-105 tests: ORGANIC CLAY, site-wide (owner, Nov 13, five refs).

The five reference designs (Synttactic clay dashboard, glowing-wave
button states, MyDocs dark/light curve, Dali blob board, MyDocs two
phones) are applied to the whole site: warm cream base, sky/mint
accents, 30px clay cards, pill button states, Me two-tone hero with
a glowing snake wave divider, blob widgets. The old pink accent is
gone from the served stylesheet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase105.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as c:
    css = c.get("/webapp/style.css").text
    # New Organic Clay tokens.
    for marker in ("#F6F1E7", "#3E8FD0", "#8ED4F7", "#3A2E33",
                   "#A8D8F8", "#7FC8B5", "#58B0E6"):
        assert marker in css, marker
    # Old pink accent is gone from the served stylesheet.
    for gone in ("#FF8FBE", "#E84393", "#F8EAF1", "#472A3E"):
        assert gone not in css, gone
    # Clay cards grew to 30px radii (the last occurrence of the
    # shared card selector is the clay block; the glass block above
    # it carries no radius).
    rules = css.split(
        ".post, .card, .task-card, .mon-card, .rank-row, .game-card, .user-row {"
    )
    assert "border-radius: 30px" in rules[-1].split("}")[0], rules[-1][:200]
    # Pill button state system (button-states reference).
    for marker in (".btn {", ".btn:hover", ".btn.is-active",
                   ".btn.is-loading", ".btn.is-success", ".btn:disabled"):
        assert marker in css, marker
    # Me two-tone hero + glowing snake wave divider.
    for marker in (".profile-hero", ".wave-div", ".wave-fill",
                   ".wave-line", "drop-shadow(0 0 6px rgba(88,176,230,.6))",
                   "linear-gradient(160deg, #A8D8F8, #7FC8B5 55%, #58B0E6)"):
        assert marker in css, marker
    # Blob widgets (Dali board reference).
    for marker in (".blob", ".nexa-stage.blob", ".suggest-card.blob"):
        assert marker in css, marker
    print("organic clay tokens + components OK")

    html = c.get("/webapp/").text
    assert "app.js?v=105" in html and "style.css?v=105" in html
    assert 'id="composer-post" class="btn"' in html
    assert 'id="design-post" type="button" class="btn"' in html
    assert 'class="nexa-stage blob"' in html
    print("asset version + button/blob wiring OK")

    js = c.get("/webapp/app.js").text
    for marker in ("profile-hero", "wave-div", "wave-fill", "wave-line",
                   "suggest-card blob", "task-claim btn", "wide btn",
                   "is-success", '"#3E8FD0"',
                   '"linear-gradient(90deg,#8ED4F7,#FBB931,#7BE0A3,#38BDF8)"'):
        assert marker in js, marker
    print("profile hero + wave + button states in JS OK")

print("PHASE 105 OK")
