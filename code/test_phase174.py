"""Phase 174 tests: Mute.

POST /users/{id}/mute toggles a one-way silent hide;
GET /me/muted lists it. The muted member's posts,
comments and stories disappear from the muter's feed
(Explore/Following/Hashtags), Trending, hashtag feed,
comment lists and story tray — including reposts of
their posts. DMs are unchanged, no notification is
sent, follows stay, and block stays stronger.
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase174.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _run_scheduled_sweep  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import ratelimit  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(1741, "Alice", "alice")
BOB = H(1742, "Bob", "bob")
CAROL = H(1743, "Carol", "carol")
DAVE = H(1744, "Dave", "dave")
EVE = H(1745, "Eve", "eve")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()

c = TestClient(app)


def mk(uid, name, username):
    """Create the user row (first authed call) and pin the username
    directly, so mention lookup never depends on auth upsert."""
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        u = db.get(models.User, uid)
        assert u is not None, "user %s not created" % uid
        u.username = username
        db.commit()
    finally:
        db.close()


for uid, name, uname in ((1741, "Alice", "alice"), (1742, "Bob", "bob"),
                         (1743, "Carol", "carol"), (1744, "Dave", "dave"),
                         (1745, "Eve", "eve")):
    mk(uid, name, uname)



# --- mute test helpers -------------------------------------------------------
from app.main import _muted_ids  # noqa: E402


def mkpost(headers, caption):
    r = c.post("/posts", json={"type": "text", "caption": caption},
               headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def mkcomment(headers, post_id, text, parent_id=None):
    body = {"text": text}
    if parent_id:
        body["parent_id"] = parent_id
    r = c.post(f"/posts/{post_id}/comments", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def feed_ids(headers, tab="explore"):
    r = c.get(f"/feed?tab={tab}", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def comment_authors(headers, post_id):
    r = c.get(f"/posts/{post_id}/comments", headers=headers)
    assert r.status_code == 200, r.text
    out = []
    for cm in r.json()["comments"]:
        out.append(cm["user_id"])
        out += [rp["user_id"] for rp in cm.get("replies", [])]
    return out


def story_authors(headers):
    r = c.get("/stories", headers=headers)
    assert r.status_code == 200, r.text
    return [g["author"]["telegram_id"] for g in r.json()["groups"]]


def mkstory(uid, file_id):
    db = SessionLocal()
    try:
        s = models.Story(user_id=uid, media_file_id=file_id,
                         created_at=datetime.utcnow())
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def mute(headers, uid):
    r = c.post(f"/users/{uid}/mute", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["muted"]


# 1. Toggle + list + profile flag + no notification + guards.
assert mute(ALICE, 1742) is True
r = c.get("/me/muted", headers=ALICE)
assert r.status_code == 200, r.text
assert [m["telegram_id"] for m in r.json()["muted"]] == [1742], r.text
r = c.get("/users/1742", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["muted_by_me"] is True, r.text
db = SessionLocal()
try:
    assert db.query(models.Notification).filter_by(
        user_id=1742, actor_id=1741).count() == 0
    assert _muted_ids(db, 1741) == {1742}
finally:
    db.close()
assert mute(ALICE, 1742) is False
r = c.get("/me/muted", headers=ALICE)
assert r.json()["muted"] == [], r.text
r = c.post("/users/1741/mute", headers=ALICE)
assert r.status_code == 400, r.text
r = c.post("/users/9999/mute", headers=ALICE)
assert r.status_code == 404, r.text
r = c.post("/users/1/mute", headers=ALICE)
assert r.status_code == 400, r.text
print("1. mute toggle + list + guards OK")

# 2. Feed (Explore + Following): muted posts vanish for the muter only.
bob_post = mkpost(BOB, "Bob's first post")
alice_post = mkpost(ALICE, "Alice's post")
assert bob_post in feed_ids(ALICE, "explore")
r = c.post("/users/1742/follow", headers=ALICE)
assert r.status_code == 200, r.text
assert bob_post in feed_ids(ALICE, "following")
assert mute(ALICE, 1742) is True
assert bob_post not in feed_ids(ALICE, "explore")
assert bob_post not in feed_ids(ALICE, "following")
assert bob_post in feed_ids(CAROL, "explore")
assert alice_post in feed_ids(BOB, "explore")
print("2. feed hide OK")

# 3. A repost of a muted author's post does not surface it either.
r = c.post(f"/posts/{bob_post}/repost", headers=CAROL)
assert r.status_code == 200, r.text
assert r.json()["reposted"] is True, r.text
# A repost resolves to its original in the feed, so the check is on
# the original's id: Alice must still not see Bob's post at all
# (the repost does not leak it), while Carol sees it.
assert bob_post not in feed_ids(ALICE, "explore")
assert bob_post in feed_ids(CAROL, "explore")
print("3. repost of muted author OK")

# 4. Comments: muted author's comment + its replies vanish for the muter.
carol_post = mkpost(CAROL, "Carol's post")
bob_cm = mkcomment(BOB, carol_post, "Bob's comment here")
dave_reply = mkcomment(DAVE, carol_post, "Dave replies to Bob",
                       parent_id=bob_cm)
# Bob is muted from section 2 — unmute first to see the comments,
# then mute again and confirm they vanish for Alice only.
assert mute(ALICE, 1742) is False  # unmute
assert 1742 in comment_authors(ALICE, carol_post)
assert 1744 in comment_authors(ALICE, carol_post)
assert 1742 in comment_authors(CAROL, carol_post)
assert mute(ALICE, 1742) is True  # mute again
assert 1742 not in comment_authors(ALICE, carol_post)
assert 1744 not in comment_authors(ALICE, carol_post)
assert 1742 in comment_authors(CAROL, carol_post)
print("4. comments hide OK")

# 5. Trending: a muted author's hot post never trends for the muter.
r = c.post(f"/posts/{bob_post}/like", headers=CAROL)
assert r.status_code == 200, r.text
r = c.get("/trending/posts", headers=ALICE)
assert r.status_code == 200, r.text
assert bob_post not in [p["id"] for p in r.json()["posts"]], r.text
r = c.get("/trending/posts", headers=CAROL)
assert bob_post in [p["id"] for p in r.json()["posts"]], r.text
print("5. trending hide OK")

# 6. Hashtag feed: muted author's tagged post disappears.
r = c.post("/hashtags/tech/follow", headers=ALICE)
assert r.status_code == 200, r.text
tech_post = mkpost(BOB, "Bob on #tech today")
r = c.get("/feed/hashtags", headers=ALICE)
assert r.status_code == 200, r.text
assert tech_post not in [p["id"] for p in r.json()["posts"]], r.text
r = c.get("/feed/hashtags", headers=CAROL)
assert r.status_code == 200, r.text
# Carol follows no tags, so she sees nothing — check via Dave instead.
r = c.post("/hashtags/tech/follow", headers=DAVE)
assert r.status_code == 200, r.text
r = c.get("/feed/hashtags", headers=DAVE)
assert tech_post in [p["id"] for p in r.json()["posts"]], r.text
print("6. hashtag feed hide OK")

# 7. Stories: muted author's group leaves the tray; unmute restores it.
mkstory(1742, "story_file_bob")
# Bob is muted from section 2, so his story is already hidden for Alice.
assert 1742 not in story_authors(ALICE)
assert mute(ALICE, 1742) is False  # unmute
assert 1742 in story_authors(ALICE)
assert mute(ALICE, 1742) is True   # mute again
assert 1742 not in story_authors(ALICE)
# A non-muter who follows Bob still sees the story.
r = c.post("/users/1742/follow", headers=CAROL)
assert r.status_code == 200, r.text
assert 1742 in story_authors(CAROL)
print("7. stories hide OK")

# 8. DMs unchanged + the muted member still sees the muter's posts.
r = c.post("/messages/1742", json={"text": "hi Bob"}, headers=ALICE)
assert r.status_code == 200, r.text
r = c.post("/messages/1741", json={"text": "hi Alice"}, headers=BOB)
assert r.status_code == 200, r.text
assert alice_post in feed_ids(BOB, "explore")
print("8. DMs + reverse visibility OK")

# 9. Mute + block: block stays stronger; unblocking restores the mute state.
# (Checked on tech_post, never reposted. A repost of a BLOCKED
# author used to leak through the feed's repost loop — fixed
# in Phase 177, covered by test_phase177.py §1-2.)
r = c.post("/users/1742/block", headers=ALICE)
assert r.status_code == 200, r.text
assert mute(ALICE, 1742) is False  # unmute while blocked
assert tech_post not in feed_ids(ALICE, "explore")
r = c.post("/users/1742/block", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["blocked"] is False
assert tech_post in feed_ids(ALICE, "explore")
print("9. mute + block interplay OK")

# 10. Client markers, version, routes, backup tables.
JS_MARKS = ["paintMute", "loadMuted", "Muted members", "/mute",
            "muted_by_me", "Member muted", "Nobody muted.", "Unmute"]
for m in JS_MARKS:
    assert m in JS, f"missing JS marker: {m}"
assert HTML.count("?v=194") == 10, HTML.count("?v=194")
assert "?v=17" + "3" not in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert "/?v=194" in BOT and "/?v=17" + "3" not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 184, len(paths)
assert "/users/{telegram_id}/mute" in paths
assert "/me/muted" in paths
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
b = r.json()
assert len(b["tables"]) == 52, len(b["tables"])
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
print("10. client + version + routes + backup OK")

print("PHASE 174 OK")
