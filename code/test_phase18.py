"""Phase-18 tests: the in-app Admin Panel + AdsGram groundwork.
Backend: /auth exposes is_admin (+ adsgram_block_id), new admin reads
(/admin/stats, /admin/users with search, /admin/posts) are admin-only,
and the ban guard refuses to ban the official account or an admin.
Frontend: the Admin view, the hidden drawer item, and the AdsGram
loader are wired in app.js / index.html / style.css."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase18.db"

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


ALICE = make_init_data({"id": 111, "first_name": "Alice", "username": "alice"})
BOB = make_init_data({"id": 222, "first_name": "Bob", "username": "bob"})
HA = {"X-Init-Data": ALICE}
HB = {"X-Init-Data": BOB}

with TestClient(app) as c:
    ra = c.post("/auth", json={"initData": ALICE}).json()
    rb = c.post("/auth", json={"initData": BOB}).json()
    assert ra["is_admin"] is True and rb["is_admin"] is False
    assert "adsgram_block_id" in ra and ra["adsgram_block_id"] == ""
    print("auth is_admin + adsgram_block_id OK")

    for path in ("/admin/stats", "/admin/users", "/admin/posts"):
        r = c.get(path, headers=HB)
        assert r.status_code == 403, (path, r.status_code)
    print("non-admin blocked from panel reads OK")

    post = c.post("/posts", headers=HB,
                  json={"type": "text", "caption": "Bob's post"}).json()

    s = c.get("/admin/stats", headers=HA).json()
    for key in ("users", "posts", "comments", "open_reports",
                "banned_users", "total_points"):
        assert key in s, key
    assert s["users"] >= 2 and s["posts"] >= 1
    print("admin stats OK", {k: s[k] for k in ("users", "posts")})

    users = c.get("/admin/users", headers=HA).json()["users"]
    assert any(u["telegram_id"] == 222 for u in users)
    found = c.get("/admin/users?q=bob", headers=HA).json()["users"]
    assert len(found) == 1 and found[0]["telegram_id"] == 222, found
    print("admin user search OK")

    posts = c.get("/admin/posts", headers=HA).json()["posts"]
    assert any(p["id"] == post["id"] for p in posts)
    print("admin post list OK")

    r = c.post("/admin/ban", headers=HA, json={"telegram_id": 1, "banned": True})
    assert r.status_code == 400, r.status_code
    r = c.post("/admin/ban", headers=HA, json={"telegram_id": 111, "banned": True})
    assert r.status_code == 400, r.status_code
    print("ban guard (official + admins protected) OK")

    html = c.get("/webapp/").text
    assert 'id="view-admin"' in html and 'id="drawer-admin"' in html
    js = c.get("/webapp/app.js").text
    for marker in ("loadAdmin", "applyAdminVisibility", "initAds",
                   "Adsgram", "maybeShowAd"):
        assert marker in js, marker
    css = c.get("/webapp/style.css").text
    assert ".admin-stats" in css and ".stat-card" in css
    print("admin panel + ads frontend wiring OK")

print("PHASE-18 TESTS PASSED")
