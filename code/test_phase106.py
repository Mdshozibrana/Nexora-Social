"""Phase-106 tests: PROFILE HERO INSET FIX (owner, Nov 13).

Owner report (from his phone, after Phase 105 went live): "Folloer
ar Bio ekpashe hoye geche" — bio + followers sat flush to the
gradient edge. Cause: .profile-hero had padding "0 0 72px" (no side
inset), while the approved mockups inset hero content 48px on a
720px canvas. Fix: 16px side padding so avatar row, bio and
followers sit inset from the hero edge; the cover banner insets
with them, as a rounded banner inside the gradient.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase106.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as c:
    css = c.get("/webapp/style.css").text
    # Hero rule carries the 16px side inset (and the old flush
    # padding is gone).
    hero = css[css.index(".profile-hero {"):]
    hero = hero[:hero.index("}")]
    assert "padding: 0 16px 72px;" in hero, hero
    assert "padding: 0 0 72px;" not in css
    # Phase 105 hero survives: gradient, wave divider, blob shapes.
    for marker in ("linear-gradient(160deg, #A8D8F8, #7FC8B5 55%, #58B0E6)",
                   ".wave-div", ".wave-line", ".blob"):
        assert marker in css, marker
    print("hero inset + Phase 105 markers OK")

    html = c.get("/webapp/").text
    for asset in ("style.css?v=115", "app.js?v=115", "games.js?v=115"):
        assert asset in html, asset
    print("asset version ?v=115 OK")

    js = c.get("/webapp/app.js").text
    assert "hero.append(headWrap, bio, stats)" in js
    print("bio + followers still inside the hero OK")

print("PHASE 106 OK")
