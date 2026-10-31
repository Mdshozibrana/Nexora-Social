"""Phase-17 tests: Claymorphism theme (owner's reference screenshot —
soft, squishy 3D, playful) + the 3D animated bottom navigation.
Asserts the clay tokens/surfaces, the sliding nav pill element and its
spring animation, the press-squish, and the JS pill mover. The clay
section supersedes the dark palette theme (phase 15) in the cascade."""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase17.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as c:
    css = c.get("/webapp/style.css").text
    for marker in ("#F8EAF1", "#FFFBFC", "#472A3E", "--clay-shadow",
                   "--clay-inset", ".game-card:nth-child", "#nav-pill",
                   "@keyframes navBtnPop", "prefers-reduced-motion",
                   "cubic-bezier(.34, 1.45"):
        assert marker in css, marker
    print("clay theme tokens + nav animation styles OK")

    html = c.get("/webapp/").text
    assert 'id="nav-pill"' in html
    print("nav pill element OK")

    js = c.get("/webapp/app.js").text
    for marker in ("moveNavPill", "NAV_IDS", "nav-pill"):
        assert marker in js, marker
    print("nav pill mover OK")

print("PHASE-17 TESTS PASSED")
