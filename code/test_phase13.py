"""Phase-13 tests, updated in Phase 39: the side menu — originally
the slide-in drawer, now the Glassy Sidebar (a slim frosted-glass
icon rail that expands into a labelled panel). Asserts the served
webapp carries the sidebar markup (MAIN / LIBRARY / ACCOUNT,
badges, Log out), the glass styles, the sidebar logic, and the
floating pill bottom-nav."""
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
    for marker in ("hero-menu", "glassbar", "gb-toggle", "gb-logo",
                   'data-go="feed"', 'data-go="videos"',
                   'data-go="designs"', 'data-go="games"',
                   'data-go="tasks"', 'data-go="leaderboard"',
                   'data-go="messages"', 'data-go="notifications"',
                   'data-go="saved"', 'data-go="shared"',
                   'data-go="profile"', 'data-go="search"',
                   "badge-saved", "badge-shared", "gb-logout",
                   "gb-msg-badge", "gb-bell-badge", "gb-foot",
                   "CONNECT ANYWHERE", "Log out"):
        assert marker in html, marker
    assert "drawer-wrap" not in html
    print("sidebar markup OK")

    css = c.get("/webapp/style.css").text
    for marker in ("#glassbar", ".gb-item.active", ".gb-badge",
                   "backdrop-filter: blur(18px)",
                   "border-radius: 999px", ".bottom-nav button.active"):
        assert marker in css, marker
    print("sidebar + pill-nav styles OK")

    js = c.get("/webapp/app.js").text
    for marker in ("openSidebar", "closeSidebar", "toggleSidebar",
                   "syncSidebarActive", "gb-logout",
                   'removeItem("nx_remember")',
                   "/me/saved", "/me/shared"):
        assert marker in js, marker
    print("sidebar logic OK")

print("PHASE-13 TESTS PASSED")
