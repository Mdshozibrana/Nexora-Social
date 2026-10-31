"""Phase-12 tests: entry screens + glass theme — /auth reports is_new
(new members land on Sign Up, returning members on Login), and the
served webapp carries the entry markup and the glass stylesheet."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase12.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


with TestClient(app) as c:
    d = make_init_data({"id": 4242, "first_name": "New User", "username": "newbie"})
    r1 = c.post("/auth", json={"initData": d})
    assert r1.json()["is_new"] is True, r1.json()
    r2 = c.post("/auth", json={"initData": d})
    assert r2.json()["is_new"] is False, r2.json()
    print("is_new: first visit True, returning False OK")

    html = c.get("/webapp/").text
    for marker in ("entry-screen", "entry-disc", "entry-go", "entry-toggle",
                   "entry-remember", "Sign up", "Login"):
        assert marker in html, marker
    css = c.get("/webapp/style.css").text
    assert "backdrop-filter" in css and ".entry-disc" in css
    assert "entry-field" in css
    js = c.get("/webapp/app.js").text
    assert "paintEntry" in js and "nx_remember" in js and "Sign Up" in js
    print("entry markup + glass stylesheet + entry logic served OK")

print("PHASE-12 TESTS PASSED")
