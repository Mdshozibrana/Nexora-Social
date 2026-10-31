"""Phase-14 tests: social-size post media + GlassMorphism system —
feed media is wrapped in the 4:5 .post-media frame (with a glass play
badge for videos), and the stylesheet carries the glass design tokens."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase14.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as c:
    css = c.get("/webapp/style.css").text
    for marker in ("--glass-bg", "--glass-blur", "aspect-ratio: 4 / 5",
                   ".post-media", ".play-badge", "object-fit: cover",
                   "blur(18px) saturate(1.5)"):
        assert marker in css, marker
    print("glass tokens + 4:5 media frame styles OK")

    js = c.get("/webapp/app.js").text
    assert 'className = "post-media"' in js
    assert 'className = "play-badge"' in js
    print("media framing logic OK")

print("PHASE-14 TESTS PASSED")
