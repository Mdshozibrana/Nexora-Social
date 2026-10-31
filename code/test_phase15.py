"""Phase-15 tests: owner palette theme — the stylesheet carries the
exact palette hexes (#121212 base, #1F2937 surface, #334155 raised,
#64748B muted, #F1F5F9 text, #EC4899 accent) and the games' buttons
use the pink accent too. NOTE: the palette theme was superseded by
the Claymorphism theme in phase 17; these hexes remain in the layered
stylesheet (and #EC4899 remains the brand accent throughout)."""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase15.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as c:
    css = c.get("/webapp/style.css").text
    for hexcode in ("#121212", "#1F2937", "#334155", "#64748B",
                    "#F1F5F9", "#EC4899"):
        assert hexcode in css, hexcode
    assert "--ink: #F1F5F9" in css
    print("palette hexes present in stylesheet OK")

    js = c.get("/webapp/games.js").text
    assert "#EC4899" in js
    print("games accent updated OK")

print("PHASE-15 TESTS PASSED")
