"""Phase-13 tests: side drawer menu + floating pill bottom-nav —
the owner's panel-design round. Asserts the served webapp carries the
drawer markup (Menu / Library / Account, badges, Log out), the drawer
and capsule styles, and the drawer logic."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase13.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as c:
    html = c.get("/webapp/").text
    for marker in ("hero-menu", "drawer-wrap", "drawer-close", "drawer-logo",
                   'data-go="feed"', 'data-go="videos"', 'data-go="games"',
                   'data-go="tasks"', 'data-go="leaderboard"',
                   'data-go="saved"', 'data-go="shared"',
                   'data-go="profile"', 'data-go="search"',
                   "badge-saved", "badge-shared", "drawer-logout",
                   "CONNECT ANYWHERE", "Log out"):
        assert marker in html, marker
    print("drawer markup OK")

    css = c.get("/webapp/style.css").text
    for marker in ("#drawer", ".drawer-item.active", ".drawer-badge",
                   "border-radius: 999px", ".bottom-nav button.active"):
        assert marker in css, marker
    print("drawer + pill-nav styles OK")

    js = c.get("/webapp/app.js").text
    for marker in ("openDrawer", "closeDrawer", "syncDrawerActive",
                   "drawer-logout", 'removeItem("nx_remember")',
                   "/me/saved", "/me/shared"):
        assert marker in js, marker
    print("drawer logic OK")

print("PHASE-13 TESTS PASSED")
