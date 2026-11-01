"""Phase-20 tests: (A) the admin-visibility fix — the .drawer-item
{display:flex} rule silently overrode the HTML `hidden` attribute, so
the Admin Panel entry showed for EVERY member (the API itself always
403'd; this locks the CSS + showView guard so the shell stays private
too); (B) in-app notifications — like/comment/follow/share rows, the
unread badge count, mark-read, self-actions excluded, broadcasts land
as announcements; (C) managed users — admin-only creation in the
reserved 9.000.000.00x id range, and Act-as: admins may operate a
managed account, nobody can act as a real member, non-admins cannot
act as anyone, and admin endpoints stay shut while acting.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase20.db"
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
C = H(603, "Chitra")

with TestClient(app) as c:
    for h in (OWNER, A, B, C):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # --- (A) visibility regression locks -------------------------------
    css = open("webapp/style.css").read()
    assert "[hidden] { display: none !important; }" in css
    js = open("webapp/app.js").read()
    assert 'name === "admin" && !(me && me.is_admin)' in js
    assert '"notifications"' in js and "loadNotifications" in js
    assert 'id="drawer-admin" data-go="admin" hidden' in \
        open("webapp/index.html").read()
    print("visibility fix locks OK")

    # --- (C) managed users: admin-only creation -------------------------
    r = c.post("/admin/fake-users", headers=A,
               json={"first_name": "Nope"})
    assert r.status_code == 403, r.status_code
    r = c.post("/admin/fake-users", headers=OWNER,
               json={"first_name": "Test User", "username": "testuser",
                     "count": 2, "country": "Bangladesh"})
    assert r.status_code == 200, r.text
    made = r.json()["created"]
    assert len(made) == 2, made
    fid1, fid2 = made[0]["telegram_id"], made[1]["telegram_id"]
    assert fid1 >= 9000000001 and fid2 == fid1 + 1, made
    assert made[0]["first_name"] == "Test User 1"
    assert made[0]["username"] == "testuser1", made
    r = c.get("/admin/users?managed=1", headers=OWNER)
    rows = {u["telegram_id"]: u for u in r.json()["users"]}
    assert rows[fid1]["is_managed"] is True, rows
    r = c.get(f"/admin/users/{fid1}", headers=OWNER)
    assert r.json()["is_managed"] is True
    assert r.json()["following"] >= 1  # auto-follows the official account
    assert r.json()["country"] == "Bangladesh"
    print("managed user creation OK")

    # --- (C) act-as security matrix --------------------------------------
    # non-admin cannot act as anyone
    r = c.post("/posts", headers=H(602, "Bilal", act_as=fid1),
               json={"type": "text", "caption": "intruder"})
    assert r.status_code == 403, r.status_code
    # admin cannot act as a REAL member
    r = c.post("/posts", headers=H(777, "Owner", act_as=601),
               json={"type": "text", "caption": "impersonation"})
    assert r.status_code == 403, r.status_code
    # admin CAN act as a managed user: the post is the managed user's
    r = c.post("/posts", headers=H(777, "Owner", act_as=fid1),
               json={"type": "text", "caption": "hello from managed"})
    assert r.status_code == 200, r.text
    assert r.json()["author_id"] == fid1, r.json()
    managed_post = r.json()["id"]
    # /auth under act-as returns the managed identity, not the admin
    r = c.post("/auth", headers={"X-Act-As": str(fid1)},
               json={"initData": OWNER["X-Init-Data"]})
    assert r.json()["telegram_id"] == fid1, r.json()
    assert r.json()["is_admin"] is False, r.json()
    # admin endpoints stay shut while acting
    r = c.get("/admin/stats", headers=H(777, "Owner", act_as=fid1))
    assert r.status_code == 403, r.status_code
    print("act-as security matrix OK")

    # --- (B) notifications ------------------------------------------------
    r = c.post("/posts", headers=A,
               json={"type": "text", "caption": "Ayesha's post"})
    post_id = r.json()["id"]
    r = c.get("/me/notifications", headers=A)
    assert r.json()["unread_count"] == 0, r.json()

    c.post(f"/posts/{post_id}/like", headers=B)
    c.post(f"/posts/{post_id}/comments", headers=B,
           json={"text": "nice one"})
    c.post("/users/601/follow", headers=B)
    r = c.get("/me/notifications", headers=A)
    d = r.json()
    assert d["unread_count"] == 3, d
    types = [n["type"] for n in d["notifications"]]
    assert types == ["follow", "comment", "like"], types
    like_row = d["notifications"][2]
    assert like_row["actor_name"] == "Bilal", like_row
    assert like_row["actor_id"] == 602 and like_row["post_id"] == post_id
    assert like_row["is_read"] is False

    # self-actions never notify
    c.post(f"/posts/{post_id}/like", headers=A)
    r = c.get("/me/notifications", headers=A)
    assert r.json()["unread_count"] == 3, r.json()

    # share: B sends A's post to C -> C is notified
    c.post(f"/posts/{post_id}/share", headers=B, json={"to_user_id": 603})
    r = c.get("/me/notifications", headers=C)
    assert r.json()["unread_count"] == 1, r.json()
    assert r.json()["notifications"][0]["type"] == "share"
    assert r.json()["notifications"][0]["actor_id"] == 602

    # the managed user's video-live style rows: broadcast announcements
    r = c.post("/admin/broadcast", headers=OWNER,
               json={"text": "Welcome everyone!"})
    assert r.status_code == 200, r.text
    r = c.get("/me/notifications", headers=A)
    assert r.json()["notifications"][0]["type"] == "announcement", r.json()
    assert "Welcome everyone!" in r.json()["notifications"][0]["text"]

    # the managed user also receives announcements (no Telegram DM exists)
    r = c.get("/me/notifications", headers=H(777, "Owner", act_as=fid2))
    assert any(n["type"] == "announcement"
               for n in r.json()["notifications"]), r.json()

    # mark read
    r = c.post("/me/notifications/read", headers=A)
    assert r.json()["unread_count"] == 0
    r = c.get("/me/notifications", headers=A)
    assert r.json()["unread_count"] == 0
    assert all(n["is_read"] for n in r.json()["notifications"])
    print("notifications flow OK")

    # --- dashboard counts the managed members ------------------------------
    r = c.get("/admin/dashboard", headers=OWNER)
    assert r.json()["managed_members"] == 2, r.json()

    # --- managed deletion rules ---------------------------------------------
    # Phase 24 supersedes the original rule (owner ordered full admin
    # control): a managed user can now be deleted completely, posts
    # and all — the old "has posts -> ban instead" 400 is gone.
    r = c.delete(f"/admin/fake-users/{fid1}", headers=OWNER)
    assert r.status_code == 200, r.status_code
    r = c.get("/admin/users?managed=1", headers=OWNER)
    assert len(r.json()["users"]) == 1
    r = c.delete(f"/admin/fake-users/{fid2}", headers=OWNER)
    assert r.status_code == 200, r.text
    r = c.get("/admin/users?managed=1", headers=OWNER)
    assert len(r.json()["users"]) == 0
    r = c.delete("/admin/fake-users/601", headers=OWNER)
    assert r.status_code == 404, r.status_code  # real members untouchable
    print("managed deletion rules OK")

    # --- frontend wiring ------------------------------------------------------
    html = open("webapp/index.html").read()
    for marker in ('id="hero-bell"', 'id="bell-badge"', 'id="view-notifications"',
                   'id="actas-banner"', 'id="admin-managed"', 'id="mu-create"'):
        assert marker in html, marker
    for marker in ("loadManaged", "paintActAs", "refreshBell", "X-Act-As",
                   "Act as"):
        assert marker in js, marker
    print("frontend wiring OK")

print("PHASE 20 ALL OK")
