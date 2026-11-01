"""Phase-21 tests: (A) the always-on bottom nav — the bar had no
z-index, so the full-screen Videos view (z-index 60) painted over it
and it "disappeared"; and showView cleared every tab highlight on
tab-less views (search/saved/shared/admin/notifications), so the
pink pill vanished and the bar looked different per screen. Locks:
nav z-index above reels, reel caption/comments clearance, and the
keep-previous-tab highlight logic. (B) Act-as Official: the owner
can now operate the official system account (@nexora, id 1) to post
and manage the platform page — still admin-only, and real members
remain impossible to impersonate.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase21.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import notify

async def fake_send(chat_id, text):
    return True

notify.send_message = fake_send

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())), "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, act_as=None):
    h = {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}
    if act_as:
        h["X-Act-As"] = str(act_as)
    return h


OWNER = H(777, "Owner")
MEMBER = H(555, "Regular")

with TestClient(app) as c:
    c.post("/auth", json={"initData": OWNER["X-Init-Data"]})
    c.post("/auth", json={"initData": MEMBER["X-Init-Data"]})

    # --- (A) nav locks -----------------------------------------------------
    css = open("webapp/style.css").read()
    assert ".bottom-nav { z-index: 65; }" in css
    assert ".reel-shade { padding-bottom: 96px; }" in css
    assert ".reel .comments { padding-bottom: 96px; }" in css
    js = open("webapp/app.js").read()
    assert "const activeBtn = navFor[name];" in js
    assert "const btn = navFor[v];" not in js  # old pill-killer is gone
    html = open("webapp/index.html").read()
    assert 'id="official-actas"' in html
    print("nav consistency locks OK")

    # --- (B) the official account exists and is public ----------------------
    r = c.get("/users/1", headers=MEMBER)
    assert r.status_code == 200, r.text
    assert r.json()["first_name"] == "Nexora Social", r.json()
    assert r.json()["is_verified"] is True

    # non-admin can NEVER act as the official account
    r = c.post("/posts", headers=H(555, "Regular", act_as=1),
               json={"type": "text", "caption": "hijack attempt"})
    assert r.status_code == 403, r.status_code

    # the owner CAN: identity, posting, and the feed shows it
    r = c.post("/auth", headers={"X-Act-As": "1"},
               json={"initData": OWNER["X-Init-Data"]})
    assert r.json()["telegram_id"] == 1, r.json()
    assert r.json()["is_admin"] is False, r.json()
    r = c.post("/posts", headers=H(777, "Owner", act_as=1),
               json={"type": "text",
                     "caption": "Official announcement post"})
    assert r.status_code == 200, r.text
    assert r.json()["author_id"] == 1, r.json()
    official_post = r.json()["id"]
    r = c.get("/feed", headers=MEMBER)
    row = [p for p in r.json()["posts"] if p["id"] == official_post]
    assert row and row[0]["author_name"] == "Nexora Social", r.json()

    # while acting as official, admin endpoints stay shut
    r = c.get("/admin/stats", headers=H(777, "Owner", act_as=1))
    assert r.status_code == 403, r.status_code

    # regressions: real members still cannot be impersonated, and the
    # official account cannot be deleted through the managed route
    r = c.post("/posts", headers=H(777, "Owner", act_as=555),
               json={"type": "text", "caption": "impersonation"})
    assert r.status_code == 403, r.status_code
    r = c.delete("/admin/fake-users/1", headers=OWNER)
    assert r.status_code == 404, r.status_code
    r = c.post("/admin/ban", headers=OWNER, json={"telegram_id": 1})
    assert r.status_code == 400, r.status_code
    print("act-as official OK")

print("PHASE 21 ALL OK")
