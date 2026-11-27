"""Phase 177 tests: blocked-repost leak fix.

A repost of a BLOCKED author's post by a third party used to show
in the feed — the feed's repost loop checked private (Phase 136)
and muted (Phase 174) originals, but not blocked ones, and
post_dict() never checked blocks at all when resolving a repost.
Now the block-pair check (either direction) applies at every
repost display site: feed, Trending, hashtag feed, saved,
collections, shared, profile, single-post view and the public
page. The repost row is never deleted — unblocking restores it.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase177.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import ratelimit  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(1771, "Alice", "alice177")
BOB = H(1772, "Bob", "bob177")
CAROL = H(1773, "Carol", "carol177")
DAVE = H(1774, "Dave", "dave177")
EVE = H(1775, "Eve", "eve177")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()

c = TestClient(app)


def mk(uid, name, username):
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


for uid, name, uname in ((1771, "Alice", "alice177"), (1772, "Bob", "bob177"),
                         (1773, "Carol", "carol177"), (1774, "Dave", "dave177"),
                         (1775, "Eve", "eve177")):
    mk(uid, name, uname)


def mkpost(headers, caption):
    r = c.post("/posts", json={"type": "text", "caption": caption},
               headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def feed_ids(headers, tab="explore"):
    r = c.get(f"/feed?tab={tab}", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def trending_ids(headers):
    r = c.get("/trending/posts", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def hashtag_ids(headers):
    r = c.get("/feed/hashtags", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def saved_ids(headers):
    r = c.get("/me/saved", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def profile_ids(headers, uid):
    r = c.get(f"/users/{uid}/posts", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def shared_ids(headers):
    r = c.get("/me/shared", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def block(headers, uid):
    r = c.post(f"/users/{uid}/block", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["blocked"]


def mute(headers, uid):
    r = c.post(f"/users/{uid}/mute", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["muted"]


def repost(headers, post_id):
    r = c.post(f"/posts/{post_id}/repost", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["reposted"]


def repost_row_id(reposter_id, orig_id):
    db = SessionLocal()
    try:
        row = db.query(models.Post).filter_by(
            user_id=reposter_id, repost_of_id=orig_id,
            is_deleted=False).first()
        assert row is not None, "repost row missing"
        return row.id
    finally:
        db.close()


# Setup: Bob posts, Carol reposts, Alice follows Carol (so the
# repost rides the Following tab too). Baseline: everyone sees it.
bob_post = mkpost(BOB, "Bob's post for 177")
assert repost(CAROL, bob_post) is True
carol_repost_row = repost_row_id(1773, bob_post)
r = c.post("/users/1773/follow", headers=ALICE)
assert r.status_code == 200, r.text
assert bob_post in feed_ids(ALICE, "explore")
assert bob_post in feed_ids(ALICE, "following")
assert bob_post in feed_ids(CAROL, "explore")
print("setup OK")

# 1. Feed: a repost of a blocked author's post is hidden, both
#    block directions; unblocking restores it (row not deleted).
assert block(ALICE, 1772) is True
assert bob_post not in feed_ids(ALICE, "explore")
assert bob_post not in feed_ids(ALICE, "following")
assert bob_post in feed_ids(CAROL, "explore")
assert block(ALICE, 1772) is False  # unblock
assert bob_post in feed_ids(ALICE, "explore")
assert block(BOB, 1771) is True  # reverse: author blocks viewer
assert bob_post not in feed_ids(ALICE, "explore")
assert bob_post in feed_ids(CAROL, "explore")
assert block(BOB, 1771) is False  # unblock
assert bob_post in feed_ids(ALICE, "explore")
print("1. feed both directions + unblock restores OK")

# 2. Your own repost of someone you later block hides the same
#    way (the card shows their content); unblock restores it.
assert repost(ALICE, bob_post) is True
assert bob_post in feed_ids(ALICE, "explore")
assert block(ALICE, 1772) is True
assert bob_post not in feed_ids(ALICE, "explore")
assert bob_post in feed_ids(CAROL, "explore")
assert block(ALICE, 1772) is False
assert bob_post in feed_ids(ALICE, "explore")
print("2. own repost after blocking OK")

# 3. Mute behaviour preserved + normal reposts unaffected.
carol_post = mkpost(CAROL, "Carol's own post")
assert repost(DAVE, carol_post) is True
assert carol_post in feed_ids(ALICE, "explore")
assert mute(ALICE, 1772) is True  # mute Bob (not blocked)
assert bob_post not in feed_ids(ALICE, "explore")
assert carol_post in feed_ids(ALICE, "explore")
assert mute(ALICE, 1772) is False
assert bob_post in feed_ids(ALICE, "explore")
print("3. mute preserved + normal reposts OK")

# 4. Trending + hashtag feed: blocked author's post never trends
#    for the blocker; their tagged original stays hidden.
r = c.post(f"/posts/{bob_post}/like", headers=CAROL)
assert r.status_code == 200, r.text
r = c.post(f"/posts/{bob_post}/like", headers=DAVE)
assert r.status_code == 200, r.text
assert bob_post in trending_ids(CAROL)
assert block(ALICE, 1772) is True
assert bob_post not in trending_ids(ALICE)
assert block(ALICE, 1772) is False
assert bob_post in trending_ids(ALICE)
r = c.post("/hashtags/tech177/follow", headers=ALICE)
assert r.status_code == 200, r.text
r = c.post("/hashtags/tech177/follow", headers=DAVE)
assert r.status_code == 200, r.text
tech_post = mkpost(BOB, "Bob on #tech177 today")
assert tech_post in hashtag_ids(ALICE)
assert tech_post in hashtag_ids(DAVE)
assert block(ALICE, 1772) is True
assert tech_post not in hashtag_ids(ALICE)
assert tech_post in hashtag_ids(DAVE)
assert block(ALICE, 1772) is False
print("4. trending + hashtag feed OK")

# 5. Saved / profile / shared / single-post view all hide the
#    blocked repost; unblock restores it. (The saved/shared rows
#    here are the REPOST row itself — a saved/shared ORIGINAL by
#    a blocked author is a separate, pre-existing gap: the saved
#    page never applied any visibility filter. See the audit.)
r = c.post(f"/posts/{carol_repost_row}/save", headers=ALICE)
assert r.status_code == 200, r.text
assert bob_post in saved_ids(ALICE)
assert bob_post in profile_ids(ALICE, 1773)  # Carol's repost row
r = c.post(f"/posts/{carol_repost_row}/share",
           json={"to_user_id": 1771}, headers=DAVE)
assert r.status_code == 200, r.text
assert bob_post in shared_ids(ALICE)
r = c.get(f"/posts/{carol_repost_row}", headers=ALICE)
assert r.status_code == 200, r.text
assert block(ALICE, 1772) is True
assert bob_post not in saved_ids(ALICE)
assert bob_post not in profile_ids(ALICE, 1773)
assert bob_post not in shared_ids(ALICE)
r = c.get(f"/posts/{carol_repost_row}", headers=ALICE)
assert r.status_code == 404, r.text
assert block(ALICE, 1772) is False
assert bob_post in saved_ids(ALICE)
assert bob_post in profile_ids(ALICE, 1773)
assert bob_post in shared_ids(ALICE)
print("5. saved/profile/shared/single-post OK")

# 6. Public page /p/: anonymous sees the post; an identified
#    viewer who blocked the author (or was blocked by them)
#    gets only the generic notice.
r = c.get(f"/p/{bob_post}")
assert r.status_code == 200, r.text
assert "Bob&#x27;s post for 177" in r.text, r.text
assert block(ALICE, 1772) is True
r = c.get(f"/p/{bob_post}", headers=ALICE)
assert r.status_code == 200, r.text
assert "Bob&#x27;s post for 177" not in r.text, r.text
assert "This post isn't public." in r.text, r.text
assert block(ALICE, 1772) is False
assert block(BOB, 1771) is True  # reverse direction
r = c.get(f"/p/{bob_post}", headers=ALICE)
assert "Bob&#x27;s post for 177" not in r.text, r.text
assert "This post isn't public." in r.text, r.text
assert block(BOB, 1771) is False
r = c.get(f"/p/{bob_post}", headers=ALICE)
assert "Bob&#x27;s post for 177" in r.text, r.text
print("6. public page both directions OK")

# 7. Client markers, version, routes, backup tables, health.
assert HTML.count("?v=202") == 10, HTML.count("?v=202")
assert "?v=17" + "7" not in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert "/?v=202" in BOT and "/?v=17" + "7" not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 193, len(paths)
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
b = r.json()
assert len(b["tables"]) == 55, len(b["tables"])
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
r = c.get("/health")
assert r.status_code == 200, r.text
h = c.get("/admin/health", headers=ADMIN).json()
assert h["version"] == 202, h
print("7. version + routes + backup + health OK")

print("PHASE 177 OK")
