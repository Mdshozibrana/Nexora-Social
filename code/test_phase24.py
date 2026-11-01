"""Phase-24 tests: FULL admin control (owner: "Admin Panel-এ
সবকিছুর পারমিশন দাও"). Covers points adjustment with ledger +
clamping, direct verify grant/revoke (official protected), profile
editing for members and the official account, comment moderation
with counter repair, complete member deletion (content wiped,
counters on other posts repaired, safety rails: official and the
admin's own account cannot be deleted), and managed users now
deletable with their posts via the full wipe.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase24.db"
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
A = H(601, "Ayesha")
B = H(602, "Bilal")

with TestClient(app) as c:
    for h in (OWNER, A, B):
        c.post("/auth", json={"initData": h["X-Init-Data"]})
    r = c.post("/posts", headers=A,
               json={"type": "text", "caption": "Ayesha's post"})
    post_id = r.json()["id"]
    c.post(f"/posts/{post_id}/like", headers=B)
    c.post(f"/posts/{post_id}/comments", headers=B,
           json={"text": "a comment to moderate"})

    # --- points: adjust, ledger, clamp, guards ------------------------------
    r = c.post("/admin/users/602/points", headers=B,
               json={"delta": 500})
    assert r.status_code == 403, r.status_code
    r = c.post("/admin/users/602/points", headers=OWNER,
               json={"delta": 150})
    assert r.status_code == 200, r.text
    assert r.json()["points"] == 150, r.json()
    r = c.get("/me/points", headers=B)
    assert any(e["reason"] == "admin_adjust" and e["amount"] == 150
               for e in r.json()["entries"]), r.json()
    r = c.post("/admin/users/602/points", headers=OWNER,
               json={"delta": -999})
    assert r.json()["points"] == 0 and r.json()["applied"] == -150, \
        r.json()
    r = c.post("/admin/users/602/points", headers=OWNER,
               json={"delta": 0})
    assert r.status_code == 400, r.status_code
    print("points control OK")

    # --- verify toggle + profile edit -----------------------------------------
    r = c.post("/admin/users/602/verify", headers=OWNER,
               json={"verified": True})
    assert r.json()["is_verified"] is True, r.json()
    r = c.get("/users/602", headers=A)
    assert r.json()["is_verified"] is True, r.json()
    r = c.post("/admin/users/602/verify", headers=OWNER,
               json={"verified": False})
    assert r.json()["is_verified"] is False, r.json()
    r = c.post("/admin/users/1/verify", headers=OWNER,
               json={"verified": False})
    assert r.status_code == 400, r.status_code  # official protected
    r = c.post("/admin/users/602/profile", headers=OWNER,
               json={"first_name": "Bilal Edited", "bio": "hello bio"})
    assert r.status_code == 200, r.text
    r = c.get("/users/602", headers=A)
    assert r.json()["first_name"] == "Bilal Edited", r.json()
    assert r.json()["bio"] == "hello bio", r.json()
    r = c.post("/admin/users/602/profile", headers=OWNER,
               json={"first_name": "   "})
    assert r.status_code == 400, r.status_code
    r = c.post("/admin/users/1/profile", headers=OWNER,
               json={"bio": "The official Nexora Social account."})
    assert r.status_code == 200, r.text
    r = c.get("/users/1", headers=A)
    assert r.json()["bio"] == "The official Nexora Social account.", \
        r.json()
    print("verify + profile control OK")

    # --- comment moderation ------------------------------------------------------
    r = c.get("/admin/comments", headers=B)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/comments", headers=OWNER)
    rows = r.json()["comments"]
    assert len(rows) == 1 and rows[0]["post_id"] == post_id, rows
    r = c.post(f"/admin/comments/{rows[0]['id']}/remove", headers=OWNER)
    assert r.status_code == 200, r.text
    r = c.get(f"/posts/{post_id}/comments", headers=A)
    assert r.json()["comments"] == [], r.json()
    r = c.get("/feed", headers=A)
    row = [p for p in r.json()["posts"] if p["id"] == post_id][0]
    assert row["comment_count"] == 0, row
    assert row["like_count"] == 1, row
    print("comment moderation OK")

    # --- full member deletion ------------------------------------------------------
    r = c.delete("/admin/users/602", headers=B)
    assert r.status_code == 403, r.status_code
    r = c.delete("/admin/users/1", headers=OWNER)
    assert r.status_code == 400, r.status_code   # official protected
    r = c.delete("/admin/users/777", headers=OWNER)
    assert r.status_code == 400, r.status_code   # cannot delete self
    r = c.delete("/admin/users/602", headers=OWNER)
    assert r.status_code == 200, r.text
    r = c.get("/users/602", headers=A)
    assert r.status_code == 404, r.status_code
    r = c.get("/feed", headers=A)
    row = [p for p in r.json()["posts"] if p["id"] == post_id][0]
    assert row["like_count"] == 0, row  # B's like wiped, counter repaired
    print("full member deletion OK")

    # --- managed user with posts: full wipe via the fake-users route -------------
    r = c.post("/admin/fake-users", headers=OWNER,
               json={"first_name": "Wipe Test", "count": 1})
    fid = r.json()["created"][0]["telegram_id"]
    r = c.post("/posts", headers=H(777, "Owner", act_as=fid),
               json={"type": "text", "caption": "managed post"})
    managed_post = r.json()["id"]
    r = c.delete(f"/admin/fake-users/{fid}", headers=OWNER)
    assert r.status_code == 200, r.text
    r = c.get("/feed", headers=A)
    assert all(p["id"] != managed_post for p in r.json()["posts"]), \
        r.json()
    print("managed full wipe OK")

    # --- frontend wiring --------------------------------------------------------
    html = open("webapp/index.html").read()
    js = open("webapp/app.js").read()
    for marker in ('id="actas-admin"', 'id="admin-comments"',
                   'id="off-name"', 'id="off-bio"', 'id="off-save"'):
        assert marker in html, marker
    for marker in ("nx_open_admin", "maybeOpenAdmin", "loadAdminComments",
                   "adjustPoints", "toggleVerify", "saveMemberProfile",
                   "deleteMember", "prefillOfficial"):
        assert marker in js, marker
    print("frontend wiring OK")

print("PHASE 24 ALL OK")
