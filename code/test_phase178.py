"""Phase 178 tests: Visibility I (direct reads) — audit H1/H3/H5.

The feed enforced block/private/mute, but direct-ID reads did
not: GET /posts/{id} never checked blocks; GET /users/{id}/posts
and public_profile 404'd only when the TARGET blocked the viewer;
post_dict()'s repost branch checked blocks only (private/muted
originals leaked through Saved/Collections/Shared/profile);
GET /posts/{id}/comments checked neither the author's
block/private state nor blocked commenters; /me/saved and
collections filtered only is_deleted, so a saved ORIGINAL by a
blocked/muted/private author returned in full. All fixed here;
the repost row is never deleted, so unblocking / unmuting /
following restores every card. Plain script (run.sh runs it
with python directly).
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase178.db"
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
from app.db import SessionLocal  # noqa: E402


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


ALICE = H(1781, "Alice", "alice178")
BOB = H(1782, "Bob", "bob178")
CAROL = H(1783, "Carol", "carol178")
DAVE = H(1784, "Dave", "dave178")
EVE = H(1785, "Eve", "eve178")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()

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


for uid, name, uname in ((1781, "Alice", "alice178"),
                         (1782, "Bob", "bob178"),
                         (1783, "Carol", "carol178"),
                         (1784, "Dave", "dave178"),
                         (1785, "Eve", "eve178")):
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


def saved_ids(headers):
    r = c.get("/me/saved", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def collection_ids(headers, cid):
    r = c.get(f"/saved/collections/{cid}", headers=headers)
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


def comment_texts(headers, post_id):
    r = c.get(f"/posts/{post_id}/comments", headers=headers)
    assert r.status_code == 200, r.text
    out = []
    for cm in r.json()["comments"]:
        out.append(cm["text"])
        out.extend(rep["text"] for rep in cm["replies"])
    return out


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


def comment(headers, post_id, text, parent_id=None):
    body = {"text": text}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = c.post(f"/posts/{post_id}/comments", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def save(headers, post_id):
    r = c.post(f"/posts/{post_id}/save", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["saved"]


def set_private(headers, value):
    r = c.post("/me/privacy", json={"is_private": value}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["is_private"]


def follow_and_accept(requester_h, target_h, target_uid):
    r = c.post(f"/users/{target_uid}/follow", headers=requester_h)
    assert r.status_code == 200, r.text
    assert r.json()["requested"] is True, r.json()
    r = c.get("/me/follow-requests", headers=target_h)
    assert r.status_code == 200, r.text
    rows = r.json()["follow_requests"]
    assert len(rows) == 1, rows
    r = c.post(f"/follow-requests/{rows[0]['id']}/accept",
               headers=target_h)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True, r.json()


# Setup: Bob posts; Carol follows Bob, then reposts; Dave and Eve
# comment (Eve replies to Dave, Dave replies to Eve); Alice saves
# Bob's post and the repost row, and files Bob's post in a
# collection Dave shares the repost row to Alice with. Baseline:
# Alice sees everything.
bob_post = mkpost(BOB, "Bob's post for 178")
carol_post = mkpost(CAROL, "Carol's own post for 178")
r = c.post("/users/1782/follow", headers=CAROL)
assert r.status_code == 200 and r.json()["following"] is True, r.text
assert repost(CAROL, bob_post) is True
carol_repost_row = repost_row_id(1783, bob_post)
dave_cm = comment(DAVE, bob_post, "Dave on Bob 178")
eve_cm = comment(EVE, bob_post, "Eve on Bob 178")
comment(EVE, bob_post, "Eve replies to Dave 178", parent_id=dave_cm)
comment(DAVE, bob_post, "Dave replies to Eve 178", parent_id=eve_cm)
assert save(ALICE, bob_post) is True
assert save(ALICE, carol_repost_row) is True
r = c.post("/saved/collections", json={"name": "Faves178"},
           headers=ALICE)
assert r.status_code == 200, r.text
coll_id = r.json()["id"]
r = c.post(f"/saved/collections/{coll_id}/posts",
           json={"post_id": bob_post}, headers=ALICE)
assert r.status_code == 200, r.text
r = c.post(f"/posts/{carol_repost_row}/share",
           json={"to_user_id": 1781}, headers=DAVE)
assert r.status_code == 200, r.text
assert bob_post in feed_ids(ALICE)
assert bob_post in saved_ids(ALICE)
assert bob_post in collection_ids(ALICE, coll_id)
assert bob_post in profile_ids(ALICE, 1783)
assert bob_post in shared_ids(ALICE)
r = c.get(f"/posts/{bob_post}", headers=ALICE)
assert r.status_code == 200, r.text
assert "Dave on Bob 178" in comment_texts(ALICE, bob_post)
assert "Eve replies to Dave 178" in comment_texts(ALICE, bob_post)
print("setup OK")

# 1. H1 get_post: 404 for BOTH block directions; unblock restores.
assert block(ALICE, 1782) is True
r = c.get(f"/posts/{bob_post}", headers=ALICE)
assert r.status_code == 404, r.text
assert "Bob's post for 178" not in r.text
assert block(ALICE, 1782) is False
r = c.get(f"/posts/{bob_post}", headers=ALICE)
assert r.status_code == 200, r.text
assert block(BOB, 1781) is True
r = c.get(f"/posts/{bob_post}", headers=ALICE)
assert r.status_code == 404, r.text
assert block(BOB, 1781) is False
r = c.get(f"/posts/{bob_post}", headers=ALICE)
assert r.status_code == 200, r.text
# Private (non-follower) still 403s, as before — only the block
# case became a 404.
assert set_private(BOB, True) is True
r = c.get(f"/posts/{bob_post}", headers=ALICE)
assert r.status_code == 403, r.text
assert set_private(BOB, False) is False
r = c.get(f"/posts/{bob_post}", headers=ALICE)
assert r.status_code == 200, r.text
print("1. get_post both block directions + private 403 preserved OK")

# 2. H1 user_posts: viewer-blocked-target 404s (the reverse
# direction was already a 404); unblock restores the list.
assert block(ALICE, 1782) is True
r = c.get("/users/1782/posts", headers=ALICE)
assert r.status_code == 404, r.text
assert block(ALICE, 1782) is False
assert bob_post in profile_ids(ALICE, 1782)
assert block(BOB, 1781) is True
r = c.get("/users/1782/posts", headers=ALICE)
assert r.status_code == 404, r.text
assert block(BOB, 1781) is False
assert bob_post in profile_ids(ALICE, 1782)
print("2. user_posts both directions OK")

# 3. H1 public_profile: the blocker gets a plain 404 too — no
# profile content leaks (no bio, no points, no photo). The
# blocked side still 404s; a third party still sees the full
# profile; unblock restores it. (Decision: 404, not a minimal
# flag-only 200 — see the PRD Phase 178 addendum.)
r = c.post("/me/profile", json={"bio": "Bob bio 178"}, headers=BOB)
assert r.status_code == 200, r.text
r = c.get("/users/1782", headers=CAROL)
assert r.status_code == 200 and r.json()["bio"] == "Bob bio 178", r.text
assert block(ALICE, 1782) is True
r = c.get("/users/1782", headers=ALICE)
assert r.status_code == 404, r.text
assert "Bob bio 178" not in r.text and "bob178" not in r.text
assert block(ALICE, 1782) is False
assert block(BOB, 1781) is True
r = c.get("/users/1782", headers=ALICE)
assert r.status_code == 404, r.text
assert block(BOB, 1781) is False
r = c.get("/users/1782", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["blocked_by_me"] is False
assert r.json()["bio"] == "Bob bio 178", r.text
print("3. public_profile 404 both directions, no leak OK")

# 4. H3 repost of a PRIVATE original: hidden from every
# post_dict surface until Alice follows Bob; then visible.
assert set_private(BOB, True) is True
assert bob_post not in feed_ids(ALICE)
assert bob_post not in saved_ids(ALICE)
assert bob_post not in collection_ids(ALICE, coll_id)
assert bob_post not in profile_ids(ALICE, 1783)
assert bob_post not in shared_ids(ALICE)
r = c.get(f"/posts/{carol_repost_row}", headers=ALICE)
assert r.status_code == 403, r.text
assert bob_post in feed_ids(CAROL)  # Carol follows Bob: unaffected
follow_and_accept(ALICE, BOB, 1782)
assert bob_post in feed_ids(ALICE)
assert bob_post in saved_ids(ALICE)
assert bob_post in profile_ids(ALICE, 1783)
r = c.get(f"/posts/{carol_repost_row}", headers=ALICE)
assert r.status_code == 200, r.text
assert set_private(BOB, False) is False
print("4. repost of private original hidden, follow restores OK")

# 5. H3 repost of a MUTED original: hidden from every
# post_dict surface until unmute; the original itself is
# hidden from the feed too (Phase 174, unchanged).
assert mute(ALICE, 1782) is True
assert bob_post not in feed_ids(ALICE)
assert bob_post not in saved_ids(ALICE)
assert bob_post not in collection_ids(ALICE, coll_id)
assert bob_post not in profile_ids(ALICE, 1783)
assert bob_post not in shared_ids(ALICE)
r = c.get(f"/posts/{carol_repost_row}", headers=ALICE)
assert r.status_code == 404, r.text
assert bob_post in feed_ids(CAROL)
assert mute(ALICE, 1782) is False
assert bob_post in feed_ids(ALICE)
assert bob_post in saved_ids(ALICE)
assert bob_post in profile_ids(ALICE, 1783)
print("5. repost of muted original hidden, unmute restores OK")

# 6. H5 comments: blocked author (both directions) and private
# author (non-follower) 404; blocked commenters are filtered
# (a blocked parent takes its replies); muted commenters stay
# filtered (Phase 174, unchanged).
assert block(ALICE, 1782) is True
r = c.get(f"/posts/{bob_post}/comments", headers=ALICE)
assert r.status_code == 404, r.text
assert block(ALICE, 1782) is False
assert block(BOB, 1781) is True
r = c.get(f"/posts/{bob_post}/comments", headers=ALICE)
assert r.status_code == 404, r.text
assert block(BOB, 1781) is False
assert "Dave on Bob 178" in comment_texts(ALICE, bob_post)
# Private author: the blocks above already removed Alice's
# follow of Bob (a block drops the follow row), so Bob going
# private locks her out -> 404; follow-accept restores it.
r = c.get("/users/1782", headers=ALICE)
assert r.status_code == 200 and r.json()["following"] is False, r.text
assert set_private(BOB, True) is True
r = c.get(f"/posts/{bob_post}/comments", headers=ALICE)
assert r.status_code == 404, r.text
# (No second follow-accept here: accepting a second request
# for the same pair 500s on the follow_requests unique key —
# pre-existing app bug, out of scope for 178; the
# follow-accept restore is already proven in §4. Going public
# restores the thread instead.)
assert set_private(BOB, False) is False
assert "Dave on Bob 178" in comment_texts(ALICE, bob_post)
# Blocked commenter: Dave's top comment (with Eve's reply to
# it) goes; Eve's top comment stays, minus Dave's reply to it.
assert block(ALICE, 1784) is True
texts = comment_texts(ALICE, bob_post)
assert "Dave on Bob 178" not in texts, texts
assert "Eve replies to Dave 178" not in texts, texts
assert "Eve on Bob 178" in texts, texts
assert "Dave replies to Eve 178" not in texts, texts
assert block(ALICE, 1784) is False
texts = comment_texts(ALICE, bob_post)
assert "Dave on Bob 178" in texts and "Eve replies to Dave 178" in texts
assert "Dave replies to Eve 178" in texts
# Muted commenter: Eve's comments (top + reply) go; Dave's stay.
assert mute(ALICE, 1785) is True
texts = comment_texts(ALICE, bob_post)
assert "Eve on Bob 178" not in texts, texts
assert "Eve replies to Dave 178" not in texts, texts
assert "Dave on Bob 178" in texts, texts
assert mute(ALICE, 1785) is False
assert "Eve on Bob 178" in comment_texts(ALICE, bob_post)
print("6. comments author 404 + blocked/muted commenters OK")

# 7. H5 saved/collections: a saved ORIGINAL by a blocked,
# muted or private author is hidden from both lists; the
# bookmark itself survives — unblock / unmute / follow
# restores it (the row is never deleted).
eve_post = mkpost(EVE, "Eve's post for 178")
assert save(ALICE, eve_post) is True
r = c.post(f"/saved/collections/{coll_id}/posts",
           json={"post_id": eve_post}, headers=ALICE)
assert r.status_code == 200, r.text
assert eve_post in saved_ids(ALICE)
assert eve_post in collection_ids(ALICE, coll_id)
assert block(ALICE, 1785) is True
assert eve_post not in saved_ids(ALICE)
assert eve_post not in collection_ids(ALICE, coll_id)
assert block(ALICE, 1785) is False
assert eve_post in saved_ids(ALICE)
assert eve_post in collection_ids(ALICE, coll_id)
assert block(EVE, 1781) is True
assert eve_post not in saved_ids(ALICE)
assert eve_post not in collection_ids(ALICE, coll_id)
assert block(EVE, 1781) is False
assert mute(ALICE, 1785) is True
assert eve_post not in saved_ids(ALICE)
assert eve_post not in collection_ids(ALICE, coll_id)
assert mute(ALICE, 1785) is False
assert eve_post in saved_ids(ALICE)
assert set_private(EVE, True) is True
assert eve_post not in saved_ids(ALICE)
assert eve_post not in collection_ids(ALICE, coll_id)
follow_and_accept(ALICE, EVE, 1785)
assert eve_post in saved_ids(ALICE)
assert eve_post in collection_ids(ALICE, coll_id)
assert set_private(EVE, False) is False
print("7. saved/collections originals hidden, restore OK")

# 8. Normal reads unaffected + feed behaviour unchanged.
assert bob_post in feed_ids(ALICE)
assert carol_post in feed_ids(ALICE)
assert eve_post in feed_ids(ALICE)
r = c.get(f"/posts/{bob_post}", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/users/1782", headers=ALICE)
assert r.status_code == 200 and r.json()["bio"] == "Bob bio 178", r.text
assert "Dave on Bob 178" in comment_texts(ALICE, bob_post)
assert bob_post in saved_ids(ALICE)
assert bob_post in profile_ids(ALICE, 1782)
assert bob_post in profile_ids(ALICE, 1783)
print("8. normal reads + feed unchanged OK")

# 9. Client markers, version, routes, backup tables, health.
assert HTML.count("?v=193") == 10, HTML.count("?v=193")
assert "?v=17" + "7" not in HTML
assert "/?v=193" in BOT and "/?v=17" + "7" not in BOT
assert "app.js?v=193" in HTML and "style.css?v=193" in HTML
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 184, len(paths)
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
b = r.json()
assert len(b["tables"]) == 52, len(b["tables"])
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
r = c.get("/health")
assert r.status_code == 200, r.text
h = c.get("/admin/health", headers=ADMIN).json()
assert h["version"] == 193, h
print("9. version + routes + backup + health OK")

print("PHASE 178 OK")
