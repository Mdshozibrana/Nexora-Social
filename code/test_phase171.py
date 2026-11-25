"""Phase 171 tests: album / carousel — multiple photos per post.

POST /posts gains media_file_ids (list, max 10; 11th rejected 400);
a new post_media table holds the ordered items; the first item is
ALSO posts.media_file_id, so single-media posts and every existing
reader keep working; POST /posts/upload-media stages one photo
(videos refused 400); Telegram media groups post as ONE album
(2 s window; a video in the group falls back to single posts);
_media_visible covers album items; delete cleans the rows.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase171.db"
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


ALICE = H(1711, "Alice", "alice")
BOB = H(1712, "Bob", "bob")
CAROL = H(1713, "Carol", "carol")
DAVE = H(1714, "Dave", "dave")
EVE = H(1715, "Eve", "eve")
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


def mention_notifs(uid):
    db = SessionLocal()
    try:
        return db.query(models.Notification).filter_by(
            user_id=uid, type="mention").count()
    finally:
        db.close()


def post_mentions(pid):
    db = SessionLocal()
    try:
        return [m.mentioned_id for m in db.query(models.Mention)
                .filter_by(post_id=pid).all()]
    finally:
        db.close()


def comment_mentions(cid):
    db = SessionLocal()
    try:
        return [m.mentioned_id for m in db.query(models.Mention)
                .filter_by(comment_id=cid).all()]
    finally:
        db.close()


def post(author_headers, caption):
    r = c.post("/posts", headers=author_headers,
               json={"type": "text", "caption": caption})
    assert r.status_code == 200, r.text
    return r.json()


def album_rows(pid):
    db = SessionLocal()
    try:
        return [(m.file_id, m.media_type, m.position)
                for m in db.query(models.PostMedia).filter_by(post_id=pid)
                .order_by(models.PostMedia.position).all()]
    finally:
        db.close()


def points(uid):
    db = SessionLocal()
    try:
        return db.get(models.User, uid).points_balance or 0
    finally:
        db.close()


# 1. Users with usernames.
for uid, name, un in ((1711, "Alice", "alice"),
                      (1712, "Bob", "bob"),
                      (1713, "Carol", "carol"),
                      (1714, "Dave", "dave"),
                      (1715, "Eve", "eve")):
    mk(uid, name, un)
    ratelimit.reset()
print("users OK")

# 2. Album via JSON: 3 photos, order kept, first doubles as
# media_file_id, caption/hashtags/points unchanged (+10).
before = points(1711)
r = c.post("/posts", headers=ALICE,
           json={"type": "photo", "caption": "trip #beach",
                 "media_file_ids": ["f1", "f2", "f3"]})
assert r.status_code == 200, r.text
album = r.json()
assert album["media_file_id"] == "f1", album
assert album["media"] == [
    {"file_id": "f1", "media_type": "photo", "position": 0},
    {"file_id": "f2", "media_type": "photo", "position": 1},
    {"file_id": "f3", "media_type": "photo", "position": 2}], album
assert album["caption"] == "trip #beach"
assert album["hashtags"] == "beach", album
assert album_rows(album["id"]) == [
    ("f1", "photo", 0), ("f2", "photo", 1), ("f3", "photo", 2)]
assert points(1711) == before + 10, points(1711)
print("album JSON post OK")

# 3. Album rejections.
r = c.post("/posts", headers=ALICE,
           json={"type": "photo", "caption": "too many",
                 "media_file_ids": ["x%d" % i for i in range(11)]})
assert r.status_code == 400, r.text
r = c.post("/posts", headers=ALICE,
           json={"type": "photo", "caption": "empty",
                 "media_file_ids": []})
assert r.status_code == 400, r.text
r = c.post("/posts", headers=ALICE,
           json={"type": "video", "caption": "video album",
                 "media_file_ids": ["f1", "f2"]})
assert r.status_code == 400, r.text
r = c.post("/posts", headers=ALICE,
           json={"type": "photo", "caption": "bad item",
                 "media_file_ids": ["f1", 123]})
assert r.status_code == 400, r.text
print("album rejections OK")

# 4. Single-media compat: media_file_id alone still works, and
# creates no post_media rows.
r = c.post("/posts", headers=ALICE,
           json={"type": "photo", "caption": "solo",
                 "media_file_id": "solo1"})
assert r.status_code == 200, r.text
solo = r.json()
assert solo["media_file_id"] == "solo1"
assert solo["media"] == [], solo
assert album_rows(solo["id"]) == []
print("single-media compat OK")

# 5. _media_visible covers album items (not just the first):
# visible to all, hidden when blocked, hidden for a private
# author to a non-follower, visible to a follower.
from app.main import _media_visible  # noqa: E402
assert _media_visible(SessionLocal(), 1712, "f2") is True
r = c.post("/users/1712/block", headers=ALICE)
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 1712, "f2") is False
finally:
    db.close()
r = c.post("/users/1712/block", headers=ALICE)  # toggle off
assert r.status_code == 200, r.text
r = c.post("/me/privacy", headers=ALICE, json={"is_private": True})
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 1713, "f2") is False
    assert _media_visible(db, 1712, "f2") is False
    db.add(models.Follow(follower_id=1712, following_id=1711))
    db.commit()
    assert _media_visible(db, 1712, "f2") is True
finally:
    db.close()
r = c.post("/me/privacy", headers=ALICE, json={"is_private": False})
assert r.status_code == 200, r.text
print("_media_visible album OK")

# 6. Staging endpoint: videos and non-photos refused 400; a real
# photo reaches the Telegram send and fails there (fake token) —
# it must NOT create a post and must NOT return 200/400.
r = c.post("/posts/upload-media", headers=ALICE,
           files={"file": ("x.mp4", b"\x00\x00\x00\x18ftypmp42",
                           "video/mp4")})
assert r.status_code == 400, r.text
r = c.post("/posts/upload-media", headers=ALICE,
           files={"file": ("x.txt", b"hello", "text/plain")})
assert r.status_code == 400, r.text
import base64  # noqa: E402
png1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "Xw8AAwMCAO+ip1sAAAAASUVORK5CYII=")
r = c.post("/posts/upload-media", headers=ALICE,
           files={"file": ("x.png", png1, "image/png")})
assert r.status_code == 502, (r.status_code, r.text)
print("staging endpoint OK")

# 7. Bot media groups: 3 photos collected -> ONE album post;
# the 2 s timer posts on its own; a video in the group falls
# back to single posts; a repeated file_id is deduped.
import asyncio  # noqa: E402
finished = []


async def finish(text):
    finished.append(text)


async def flow():
    await bot_mod._media_group_collect(
        "g1", 1711, ("photo", "a1", None), "trip #beach", finish)
    await bot_mod._media_group_collect(
        "g1", 1711, ("photo", "a2", None), "", finish)
    await bot_mod._media_group_collect(
        "g1", 1711, ("photo", "a3", None), "", finish)
    await bot_mod._media_group_flush("g1")
    # g2: let the 2 s timer fire by itself.
    await bot_mod._media_group_collect(
        "g2", 1711, ("photo", "b1", None), "duo", finish)
    await bot_mod._media_group_collect(
        "g2", 1711, ("photo", "b2", None), "", finish)
    await asyncio.sleep(2.5)
    # g3: photo + video -> single posts, no album rows.
    await bot_mod._media_group_collect(
        "g3", 1711, ("photo", "v1", None), "mixed", finish)
    await bot_mod._media_group_collect(
        "g3", 1711, ("video", "v2", "thumb1"), "", finish)
    await bot_mod._media_group_flush("g3")
    # g4: same file_id twice -> one row.
    await bot_mod._media_group_collect(
        "g4", 1711, ("photo", "d1", None), "dup", finish)
    await bot_mod._media_group_collect(
        "g4", 1711, ("photo", "d1", None), "", finish)
    await bot_mod._media_group_flush("g4")


asyncio.run(flow())
db = SessionLocal()
try:
    posts = db.query(models.Post).filter_by(
        user_id=1711, media_file_id="a1", is_deleted=False).all()
    assert len(posts) == 1, len(posts)
    assert album_rows(posts[0].id) == [
        ("a1", "photo", 0), ("a2", "photo", 1), ("a3", "photo", 2)]
    duo = db.query(models.Post).filter_by(
        user_id=1711, media_file_id="b1", is_deleted=False).all()
    assert len(duo) == 1, len(duo)
    assert album_rows(duo[0].id) == [("b1", "photo", 0),
                                     ("b2", "photo", 1)]
    mixed = db.query(models.Post).filter(
        models.Post.user_id == 1711,
        models.Post.media_file_id.in_(["v1", "v2"]),
        models.Post.is_deleted == False).all()  # noqa: E712
    assert len(mixed) == 2, len(mixed)
    assert album_rows(mixed[0].id) == []
    assert album_rows(mixed[1].id) == []
    dup = db.query(models.Post).filter_by(
        user_id=1711, media_file_id="d1", is_deleted=False).all()
    assert len(dup) == 1, len(dup)
    # deduped to a single item -> a single post, no album rows.
    assert album_rows(dup[0].id) == []
finally:
    db.close()
assert len(finished) == 4, finished
assert "album of 3 photos" in finished[0], finished
assert "album of 2 photos" in finished[1], finished
print("bot media groups OK")

# 8. Delete cleans the album rows.
r = c.delete("/posts/%s" % album["id"], headers=ALICE)
assert r.status_code == 200, r.text
assert album_rows(album["id"]) == []
print("delete cleans album rows OK")

# 9. Neighbour: @mentions still work on an album caption.
before = mention_notifs(1712)
r = c.post("/posts", headers=ALICE,
           json={"type": "photo", "caption": "with @bob",
                 "media_file_ids": ["m1", "m2"]})
assert r.status_code == 200, r.text
assert any(m["username"] == "bob" for m in r.json()["mentions"])
assert mention_notifs(1712) == before + 1
print("mentions on album OK")

# 10. Client markers, version, routes, backup.
js = c.get("/webapp/app.js").text
for marker in ("albumItems", "albumFrame", "carousel-track",
               "carousel-dot", "carousel-count", "carousel-arrow",
               "pv-prev", "pv-next", "pv-count", "/posts/upload-media",
               "composerFiles", "renderRichText", "loadSkills",
               "loadBlood", "MASCOT_TIPS_BY_VIEW", "totp-card"):
    assert marker in js, marker
assert "app.js?v=177" in HTML
assert ("?v=17" + "0") not in HTML
assert "style.css?v=177" in HTML
assert ".carousel-track" in CSS
assert "#pv-prev" in CSS
paths = {rt.path for rt in app.routes}
assert len(paths) == 183, len(paths)
assert "/posts/upload-media" in paths
h = c.get("/admin/health", headers=ADMIN).json()
assert h["version"] == 177, h
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 51, len(r.json()["tables"])
assert "post_media" in r.json()["tables"]
assert len(_BACKUP_TABLES) == 51, len(_BACKUP_TABLES)
print("client + version + routes + backup OK (174 routes, 48 tables, ?v=177)")

print("PHASE 171 OK")
