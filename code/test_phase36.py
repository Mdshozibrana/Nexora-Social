"""Phase-36 tests: Messages + Stories (owner: a Facebook-style
messenger in the top corner). Covers send/read/unread badges,
conversation lists, block guard, the message notification,
following list, story upload/visibility (follow-based), unique
story views, 24h expiry, and story deletion."""
import hashlib, hmac, json, os, sqlite3, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase36.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.main as main_mod


async def fake_upload(user, file, caption=""):
    return ("photo", "storyfile_" + (file.filename or "x"))


main_mod._telegram_upload_or_400 = fake_upload

from fastapi.testclient import TestClient
from app.main import app

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
for marker in ('id="hero-msg"', 'id="msg-badge"', 'id="view-messages"',
               'id="view-chat"', 'id="stories-strip"',
               'id="story-file"', 'id="story-wrap"',
               'id="gb-msg-badge"'):
    assert marker in HTML, marker
for marker in ("loadMessages", "openChat", "loadStories",
               "refreshMsgBadge", "/messages/unread"):
    assert marker in JS, marker
assert ".bubble" in CSS and "#story-wrap" in CSS
print("client contract OK")


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid,
                                           "first_name": name})}


A = H(880, "Alice")
B = H(881, "Bob")
PNG = ("s.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")

with TestClient(app) as c:
    for h in (A, B):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # --- messaging basics ---
    r = c.post("/messages/880", headers=B, json={"text": "hi Alice"})
    assert r.status_code == 200 and r.json()["mine"] is True, r.text
    r = c.get("/messages/unread", headers=A)
    assert r.json() == {"count": 1}, r.json()
    r = c.get("/messages", headers=A)
    convs = r.json()["conversations"]
    assert len(convs) == 1 and convs[0]["user"]["telegram_id"] == 881, convs
    assert convs[0]["unread"] == 1 and convs[0]["last"]["text"] == "hi Alice"
    # the recipient got a bell notification of type "message"
    notes = c.get("/me/notifications?limit=10",
                  headers=A).json()["notifications"]
    assert any(n["type"] == "message" for n in notes), notes
    r = c.get("/messages/881", headers=A)
    msgs = r.json()["messages"]
    assert len(msgs) == 1 and msgs[0]["mine"] is False, msgs
    assert c.get("/messages/unread", headers=A).json() == {"count": 0}
    r = c.post("/messages/881", headers=A, json={"text": "hello Bob"})
    assert r.status_code == 200, r.text
    r = c.get("/messages/880", headers=B)
    texts = [m["text"] for m in r.json()["messages"]]
    assert texts == ["hi Alice", "hello Bob"], texts
    r = c.post("/messages/881", headers=B, json={"text": "self"})
    assert r.status_code == 400, r.status_code
    r = c.post("/messages/424242", headers=B, json={"text": "ghost"})
    assert r.status_code == 404, r.status_code
    print("messaging OK")

    # --- block guard ---
    c.post("/users/881/follow", headers=A)
    c.post("/users/881/block", headers=A)
    r = c.post("/messages/880", headers=B, json={"text": "blocked?"})
    assert r.status_code == 403, r.status_code
    r = c.get("/messages", headers=A)
    assert r.json()["conversations"] == [], r.json()
    c.post("/users/881/block", headers=A)  # unblock
    r = c.post("/messages/880", headers=B, json={"text": "back again"})
    assert r.status_code == 200, r.text
    print("block guard OK")

    # --- following list (start-a-chat source) ---
    c.post("/users/880/follow", headers=B)
    r = c.get("/me/following", headers=B)
    ids = [u["telegram_id"] for u in r.json()["users"]]
    assert 880 in ids, ids
    print("following list OK")

    # --- stories ---
    r = c.post("/stories/upload", headers=A, files={"file": PNG})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = c.get("/stories", headers=B)
    groups = r.json()["groups"]
    mine = [g for g in groups if g["author"]["telegram_id"] == 880]
    assert len(mine) == 1 and mine[0]["has_unviewed"] is True, groups
    assert mine[0]["stories"][0]["id"] == sid
    r = c.post(f"/stories/{sid}/view", headers=B)
    assert r.json() == {"views": 1, "counted": True}, r.json()
    r = c.post(f"/stories/{sid}/view", headers=B)
    assert r.json() == {"views": 1, "counted": False}, r.json()
    r = c.post(f"/stories/{sid}/view", headers=A)
    assert r.json()["counted"] is False  # author never counts
    r = c.request("DELETE", f"/stories/{sid}", headers=B)
    assert r.status_code == 403, r.status_code
    # expiry: age the story past 24h straight in the DB
    db = sqlite3.connect("test_phase36.db")
    db.execute("UPDATE stories SET created_at = "
               "datetime('now', '-25 hours') WHERE id = ?", (sid,))
    db.commit()
    db.close()
    r = c.get("/stories", headers=B)
    assert all(g["author"]["telegram_id"] != 880
               for g in r.json()["groups"]), r.json()
    r = c.post(f"/stories/{sid}/view", headers=B)
    assert r.status_code == 404, r.status_code
    r = c.request("DELETE", f"/stories/{sid}", headers=A)
    assert r.status_code == 200, r.text
    print("stories OK")

print("PHASE-36 TESTS PASSED")
