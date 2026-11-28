"""Phase 179 tests: Visibility II (actions & discovery) — audit H2/H4/H6/H7/H8 + M1-M5.

Phase 178 fixed direct reads; this phase fixes the write paths
(H2: like/repost/poll-vote/save/add-to-collection/comment/view
now refuse invisible posts — private non-followed, blocked
either way, or muted original, effective author for reposts),
share creation (H4: the sharer must see the post; /me/shared
hides a private post shared to a non-follower), story views
(H6: block/private/mute, no StoryView row), hashtag search
(H7: mute filter + DB-level predicate, old tagged posts
findable, #art never matches #artist), trending hashtags
(H8: muted + private excluded), _media_visible mute (M1),
highlight mute (M2), public-page mute + invalid initData 401
(M3), read rate limits (M4: small test-only budgets prove the
wiring — production budgets stay generous), and cursor
pagination after filtering (M5: full pages, no empty-page gaps).
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase179.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
import app.main as main_mod  # noqa: E402
from app.main import app, _BACKUP_TABLES, _media_visible, _media_token  # noqa: E402
from app import models, ratelimit  # noqa: E402
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


ALICE = H(1791, "Alice", "alice179")
BOB = H(1792, "Bob", "bob179")
CAROL = H(1793, "Carol", "carol179")
DAVE = H(1794, "Dave", "dave179")
EVE = H(1795, "Eve", "eve179")
FRANK = H(1796, "Frank", "frank179")
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


for uid, name, uname in ((1791, "Alice", "alice179"),
                         (1792, "Bob", "bob179"),
                         (1793, "Carol", "carol179"),
                         (1794, "Dave", "dave179"),
                         (1795, "Eve", "eve179"),
                         (1796, "Frank", "frank179")):
    mk(uid, name, uname)


def mkpost(headers, caption, poll=None):
    body = {"type": "text", "caption": caption}
    if poll is not None:
        body["poll"] = poll
    r = c.post("/posts", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def db():
    return SessionLocal()


def block(headers, uid):
    r = c.post(f"/users/{uid}/block", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["blocked"]


def mute(headers, uid):
    r = c.post(f"/users/{uid}/mute", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["muted"]


def set_private(headers, value):
    r = c.post("/me/privacy", json={"is_private": value}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["is_private"]


def feed_ids(headers, tab="explore", cursor=0):
    url = f"/feed?tab={tab}" + (f"&cursor={cursor}" if cursor else "")
    r = c.get(url, headers=headers)
    assert r.status_code == 200, r.text
    j = r.json()
    return [p["id"] for p in j["posts"]], j["next_cursor"]


def walk_feed(headers):
    ids, cur, pages = [], 0, []
    while True:
        page, cur = feed_ids(headers, cursor=cur)
        pages.append(len(page))
        ids.extend(page)
        if cur is None:
            break
        assert page, "empty page with a non-null cursor"
    return ids, pages


def like_count(post_id):
    s = db()
    try:
        return s.get(models.Post, post_id).like_count
    finally:
        s.close()


def comment_count(post_id):
    s = db()
    try:
        return s.get(models.Post, post_id).comment_count
    finally:
        s.close()


def count_rows(model, **kw):
    s = db()
    try:
        return s.query(model).filter_by(**kw).count()
    finally:
        s.close()


def mkstory(uid, file_id, hours_old=0):
    s = db()
    try:
        st = models.Story(
            user_id=uid, media_file_id=file_id,
            created_at=datetime.utcnow() - timedelta(hours=hours_old))
        s.add(st)
        s.commit()
        s.refresh(st)
        return st.id
    finally:
        s.close()


def mkpost_row(uid, caption="", hashtags="", media_file_id=None,
               repost_of_id=None):
    s = db()
    try:
        p = models.Post(user_id=uid, type="repost" if repost_of_id else "text",
                        caption=caption, hashtags=hashtags,
                        media_file_id=media_file_id,
                        repost_of_id=repost_of_id)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id
    finally:
        s.close()


# Setup: Bob posts (plain + poll); Carol follows public Bob
# directly (no follow request); Alice never follows Bob.
bob_post = mkpost(BOB, "Bob's post for 179")["id"]
poll_post = mkpost(BOB, "Bob's poll for 179",
                   poll={"question": "Best pet 179?",
                         "options": ["Cats", "Dogs"]})
poll_id = poll_post["id"]
poll_opts = {o["text"]: o["id"] for o in poll_post["poll"]["options"]}
r = c.post("/users/1792/follow", headers=CAROL)
assert r.status_code == 200 and r.json()["following"] is True, r.text
print("setup OK")

# 1. H2 private: Alice (non-follower) is refused on every action
# against Bob's private post — and nothing is recorded. Carol
# (follower) passes every action; Bob's self-actions pass.
assert set_private(BOB, True) is True
for method, url, body in (
        ("POST", f"/posts/{bob_post}/like", None),
        ("POST", f"/posts/{bob_post}/comments",
         {"text": "Alice comment 179"}),
        ("POST", f"/posts/{bob_post}/repost", None),
        ("POST", f"/posts/{poll_id}/poll/vote",
         {"option_id": poll_opts["Cats"]}),
        ("POST", f"/posts/{bob_post}/save", None),
        ("POST", f"/posts/{bob_post}/view", None)):
    r = c.post(url, json=body, headers=ALICE) if body is not None \
        else c.post(url, headers=ALICE)
    assert r.status_code == 403, (url, r.status_code, r.text)
assert like_count(bob_post) == 0
assert comment_count(bob_post) == 0
assert count_rows(models.Post, user_id=1791, repost_of_id=bob_post) == 0
assert count_rows(models.PollVote, user_id=1791) == 0
assert count_rows(models.SavedPost, user_id=1791, post_id=bob_post) == 0
assert count_rows(models.PostView, user_id=1791, post_id=bob_post) == 0
r = c.post("/saved/collections", json={"name": "C179"}, headers=ALICE)
assert r.status_code == 200, r.text
coll_id = r.json()["id"]
r = c.post(f"/saved/collections/{coll_id}/posts",
           json={"post_id": bob_post}, headers=ALICE)
assert r.status_code == 403, r.text
assert count_rows(models.SavedCollectionPost, collection_id=coll_id) == 0
assert count_rows(models.SavedPost, user_id=1791, post_id=bob_post) == 0
# Carol (follower) passes everything; Bob's own actions pass.
r = c.post(f"/posts/{bob_post}/like", headers=CAROL)
assert r.status_code == 200 and r.json()["liked"] is True, r.text
r = c.post(f"/posts/{bob_post}/comments",
           json={"text": "Carol comment 179"}, headers=CAROL)
assert r.status_code == 200, r.text
r = c.post(f"/posts/{poll_id}/poll/vote",
           json={"option_id": poll_opts["Dogs"]}, headers=CAROL)
assert r.status_code == 200, r.text
r = c.post(f"/posts/{bob_post}/save", headers=CAROL)
assert r.status_code == 200 and r.json()["saved"] is True, r.text
r = c.post(f"/posts/{bob_post}/view", headers=CAROL)
assert r.status_code == 200 and r.json()["counted"] is True, r.text
r = c.post(f"/posts/{bob_post}/like", headers=BOB)
assert r.status_code == 200 and r.json()["liked"] is True, r.text
r = c.post(f"/posts/{bob_post}/comments",
           json={"text": "Bob self comment 179"}, headers=BOB)
assert r.status_code == 200, r.text
assert set_private(BOB, False) is False
print("1. H2 private refused, follower + self pass, no side effects OK")

# 2. H2 blocked: both directions 403; unblock restores.
assert block(ALICE, 1792) is True
r = c.post(f"/posts/{bob_post}/like", headers=ALICE)
assert r.status_code == 403, r.text
r = c.post(f"/posts/{bob_post}/view", headers=ALICE)
assert r.status_code == 403, r.text
assert count_rows(models.PostView, user_id=1791, post_id=bob_post) == 0
assert block(ALICE, 1792) is False
assert block(BOB, 1791) is True
r = c.post(f"/posts/{bob_post}/comments",
           json={"text": "Alice blocked comment 179"}, headers=ALICE)
assert r.status_code == 403, r.text
r = c.post(f"/posts/{bob_post}/save", headers=ALICE)
assert r.status_code == 403, r.text
assert block(BOB, 1791) is False
r = c.post(f"/posts/{bob_post}/like", headers=ALICE)
assert r.status_code == 200 and r.json()["liked"] is True, r.text
print("2. H2 blocked both directions, unblock restores OK")

# 3. H2 muted original: actions on Carol's repost of Bob's post
# (and on Bob's own post) are refused while Alice mutes Bob;
# unmute restores. The repost row itself is never deleted.
r = c.post(f"/posts/{bob_post}/repost", headers=CAROL)
assert r.status_code == 200 and r.json()["reposted"] is True, r.text
s = db()
try:
    carol_repost = s.query(models.Post).filter_by(
        user_id=1793, repost_of_id=bob_post, is_deleted=False).first().id
finally:
    s.close()
assert mute(ALICE, 1792) is True
for url, body in (
        (f"/posts/{carol_repost}/like", None),
        (f"/posts/{carol_repost}/comments", {"text": "muted repost 179"}),
        (f"/posts/{carol_repost}/repost", None),
        (f"/posts/{carol_repost}/save", None),
        (f"/posts/{carol_repost}/view", None),
        (f"/posts/{bob_post}/like", None)):
    r = c.post(url, json=body, headers=ALICE) if body is not None \
        else c.post(url, headers=ALICE)
    assert r.status_code == 403, (url, r.status_code, r.text)
r = c.post(f"/saved/collections/{coll_id}/posts",
           json={"post_id": carol_repost}, headers=ALICE)
assert r.status_code == 403, r.text
assert mute(ALICE, 1792) is False
r = c.post(f"/posts/{carol_repost}/like", headers=ALICE)
assert r.status_code == 200, r.text
r = c.post(f"/posts/{bob_post}/view", headers=ALICE)
assert r.status_code == 200 and r.json()["counted"] is True, r.text
print("3. H2 muted original refused on repost + direct, unmute restores OK")

# 4. H4 share: a non-follower cannot share a private post at all;
# a follower CAN share it, but the non-follower recipient never
# sees it in /me/shared (post_dict, Phase 178). Public again,
# the share lands and is visible.
assert set_private(BOB, True) is True
r = c.post(f"/posts/{bob_post}/share",
           json={"to_user_id": 1794}, headers=ALICE)
assert r.status_code == 403, r.text
assert count_rows(models.PostShare, from_user_id=1791,
                  post_id=bob_post) == 0
r = c.post(f"/posts/{bob_post}/share",
           json={"to_user_id": 1791}, headers=CAROL)
assert r.status_code == 200, r.text
r = c.get("/me/shared", headers=ALICE)
assert r.status_code == 200, r.text
assert all(p["id"] != bob_post for p in r.json()["posts"]), r.json()
assert set_private(BOB, False) is False
r = c.post(f"/posts/{bob_post}/share",
           json={"to_user_id": 1794}, headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/me/shared", headers=DAVE)
assert r.status_code == 200, r.text
assert bob_post in [p["id"] for p in r.json()["posts"]], r.json()
print("4. H4 share refused when invisible; shared-to-non-follower hidden OK")

# 5. H6 story view: blocked/private/muted authors are not
# view-countable by ID, and no StoryView row is created; the
# viewer never appears in the owner's viewer list. Own views
# and public views still count.
s_pub = mkstory(1792, "file179story_pub")
r = c.post(f"/stories/{s_pub}/view", headers=ALICE)
assert r.status_code == 200 and r.json()["counted"] is True, r.text
r = c.post(f"/stories/{s_pub}/view", headers=BOB)
assert r.status_code == 200 and r.json()["counted"] is False, r.text
assert set_private(BOB, True) is True
s_priv = mkstory(1792, "file179story_priv")
r = c.post(f"/stories/{s_priv}/view", headers=ALICE)
assert r.status_code == 403, r.text
assert count_rows(models.StoryView, story_id=s_priv) == 0
r = c.get(f"/stories/{s_priv}/viewers", headers=BOB)
assert r.status_code == 200, r.text
assert r.json()["viewers"] == [], r.json()
assert set_private(BOB, False) is False
s_blk = mkstory(1792, "file179story_blk")
assert block(ALICE, 1792) is True
r = c.post(f"/stories/{s_blk}/view", headers=ALICE)
assert r.status_code == 404, r.text
assert count_rows(models.StoryView, story_id=s_blk) == 0
assert block(ALICE, 1792) is False
s_blk2 = mkstory(1792, "file179story_blk2")
assert block(BOB, 1791) is True
r = c.post(f"/stories/{s_blk2}/view", headers=ALICE)
assert r.status_code == 404, r.text
assert count_rows(models.StoryView, story_id=s_blk2) == 0
assert block(BOB, 1791) is False
s_mut = mkstory(1792, "file179story_mut")
assert mute(ALICE, 1792) is True
r = c.post(f"/stories/{s_mut}/view", headers=ALICE)
assert r.status_code == 404, r.text
assert count_rows(models.StoryView, story_id=s_mut) == 0
assert mute(ALICE, 1792) is False
r = c.post(f"/stories/{s_mut}/view", headers=ALICE)
assert r.status_code == 200 and r.json()["counted"] is True, r.text
print("5. H6 story view 403/404 + no row, own/public still count OK")

# 6. H7 hashtag search: an old tagged post is findable past 100
# newer posts; #art never matches #artist; muted + private
# authors are excluded.
old_tag = mkpost(CAROL, "#oldtag179 the old one")["id"]
for i in range(105):
    mkpost_row(1794, caption=f"filler {i} for 179")
r = c.get("/search?q=%23oldtag179", headers=ALICE)
assert r.status_code == 200, r.text
assert old_tag in [p["id"] for p in r.json()["posts"]], r.json()
art_post = mkpost(BOB, "#art for 179")["id"]
artist_post = mkpost(BOB, "#artist for 179")["id"]
r = c.get("/search?q=%23art", headers=ALICE)
assert r.status_code == 200, r.text
found = [p["id"] for p in r.json()["posts"]]
assert art_post in found and artist_post not in found, found
muted_tag = mkpost(BOB, "#mutedtag179 for 179")["id"]
assert mute(ALICE, 1792) is True
r = c.get("/search?q=%23mutedtag179", headers=ALICE)
assert r.status_code == 200, r.text
assert muted_tag not in [p["id"] for p in r.json()["posts"]], r.json()
assert mute(ALICE, 1792) is False
r = c.get("/search?q=%23mutedtag179", headers=ALICE)
assert muted_tag in [p["id"] for p in r.json()["posts"]], r.json()
priv_tag = mkpost(BOB, "#privtag179 for 179")["id"]
assert set_private(BOB, True) is True
r = c.get("/search?q=%23privtag179", headers=ALICE)
assert priv_tag not in [p["id"] for p in r.json()["posts"]], r.json()
r = c.get("/search?q=%23privtag179", headers=CAROL)
assert priv_tag in [p["id"] for p in r.json()["posts"]], r.json()
assert set_private(BOB, False) is False
print("6. H7 old tag found, #art != #artist, muted/private excluded OK")

# 7. H8 trending hashtags: muted and private authors stop
# inflating tag counts; unmute / public restores them.
mkpost(BOB, "#trend179 bob one")
mkpost(ALICE, "#trend179 alice one")


def trend_count(headers, tag):
    r = c.get("/trending/hashtags?limit=20", headers=headers)
    assert r.status_code == 200, r.text
    for h in r.json()["hashtags"]:
        if h["tag"] == tag:
            return h["count"]
    return 0


assert trend_count(ALICE, "trend179") == 2, trend_count(ALICE, "trend179")
assert mute(ALICE, 1792) is True
assert trend_count(ALICE, "trend179") == 1
assert mute(ALICE, 1792) is False
assert trend_count(ALICE, "trend179") == 2
assert set_private(BOB, True) is True
assert trend_count(ALICE, "trend179") == 1
assert set_private(BOB, False) is False
assert trend_count(ALICE, "trend179") == 2
print("7. H8 trending hashtags exclude muted/private OK")

# 8. M1 _media_visible: a muted author's post / album / story /
# profile-photo media is hidden for the muter, own media still
# loads, and /media 404s before any upstream call.
media_post = mkpost_row(1792, caption="media 179",
                        media_file_id="file179bob")
s = db()
try:
    s.add(models.PostMedia(post_id=media_post, file_id="file179album"))
    s.commit()
    bob_user = s.get(models.User, 1792)
    bob_user.photo_file_id = "file179photo"
    s.commit()
finally:
    s.close()
media_story = mkstory(1792, "file179story_media")
s = db()
try:
    assert _media_visible(s, 1791, "file179bob") is True
    assert _media_visible(s, 1791, "file179album") is True
    assert _media_visible(s, 1791, "file179story_media") is True
    assert _media_visible(s, 1791, "file179photo") is True
    assert _media_visible(s, 1792, "file179bob") is True
    assert _media_visible(s, 1792, "file179photo") is True
finally:
    s.close()
assert mute(ALICE, 1792) is True
s = db()
try:
    assert _media_visible(s, 1791, "file179bob") is False
    assert _media_visible(s, 1791, "file179album") is False
    assert _media_visible(s, 1791, "file179story_media") is False
    assert _media_visible(s, 1791, "file179photo") is False
    # The muted author's own view still passes.
    assert _media_visible(s, 1792, "file179bob") is True
    assert _media_visible(s, 1792, "file179photo") is True
finally:
    s.close()
r = c.get(f"/media/file179bob?mt={_media_token(1791)}")
assert r.status_code == 404, r.text
assert mute(ALICE, 1792) is False
s = db()
try:
    assert _media_visible(s, 1791, "file179bob") is True
finally:
    s.close()
print("8. M1 media mute gate incl. /media 404, own media intact OK")

# 9. M2 highlights: a muted member's highlight circles and
# replays disappear for the muter; an expired story stays
# visible via its highlight only while unmuted.
hl_story = mkstory(1792, "file179hl_live")
hl_old = mkstory(1792, "file179hl_old", hours_old=25)
r = c.post("/highlights", json={"title": "H179",
                                "story_ids": [hl_story, hl_old]},
           headers=BOB)
assert r.status_code == 200, r.text
hl_id = r.json()["id"]
r = c.get("/highlights/user/1792", headers=ALICE)
assert r.status_code == 200, r.text
assert [h["id"] for h in r.json()["highlights"]] == [hl_id], r.json()
r = c.get(f"/highlights/{hl_id}", headers=ALICE)
assert r.status_code == 200, r.text
assert len(r.json()["stories"]) == 2, r.json()
s = db()
try:
    assert _media_visible(s, 1791, "file179hl_old") is True
finally:
    s.close()
assert mute(ALICE, 1792) is True
r = c.get("/highlights/user/1792", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["highlights"] == [], r.json()
r = c.get(f"/highlights/{hl_id}", headers=ALICE)
assert r.status_code == 404, r.text
s = db()
try:
    assert _media_visible(s, 1791, "file179hl_old") is False
finally:
    s.close()
assert mute(ALICE, 1792) is False
r = c.get("/highlights/user/1792", headers=ALICE)
assert [h["id"] for h in r.json()["highlights"]] == [hl_id], r.json()
print("9. M2 highlights hidden for muted, expired-story media gated OK")

# 10. M3 public page: muted identified viewer gets the generic
# notice; a present-but-invalid/expired header is a 401; an
# absent header stays anonymous and still works.
pub_post = mkpost(BOB, "Bob public page 179")["id"]
r = c.get(f"/p/{pub_post}")
assert r.status_code == 200 and "Bob public page 179" in r.text, r.text
r = c.get(f"/p/{pub_post}", headers=ALICE)
assert r.status_code == 200 and "Bob public page 179" in r.text, r.text
assert mute(ALICE, 1792) is True
r = c.get(f"/p/{pub_post}", headers=ALICE)
assert r.status_code == 200, r.text
assert "This post isn't public." in r.text, r.text
assert "Bob public page 179" not in r.text, r.text
assert mute(ALICE, 1792) is False
r = c.get(f"/p/{pub_post}", headers=ALICE)
assert r.status_code == 200 and "Bob public page 179" in r.text, r.text
bad = {"X-Init-Data": ALICE["X-Init-Data"] + "x"}
r = c.get(f"/p/{pub_post}", headers=bad)
assert r.status_code == 401, (r.status_code, r.text)
old_user = {"id": 1791, "first_name": "Alice", "username": "alice179"}
old_h = {"X-Init-Data": make_init_data(
    old_user, auth_date=int(time.time()) - 90000)}
r = c.get(f"/p/{pub_post}", headers=old_h)
assert r.status_code == 401, (r.status_code, r.text)
r = c.get(f"/p/{pub_post}")
assert r.status_code == 200 and "Bob public page 179" in r.text, r.text
print("10. M3 public page muted notice + 401 invalid/expired, anon OK")

# 11. M5 cursor pagination: seed mixed-visibility rows — Carol
# originals plus repost rows of Bob's (private) post — then
# walk every page: full 20-post pages until the last, no empty
# page with a non-null cursor, all of Carol's originals present.
assert set_private(BOB, True) is True
carol_orig = [mkpost_row(1793, caption=f"carol orig {i} 179")
              for i in range(25)]
for i in range(25):
    mkpost_row(1794, repost_of_id=bob_post)
ids, pages = walk_feed(FRANK)
assert all(n == 20 for n in pages[:-1]), pages
assert all(n > 0 for n in pages), pages
assert len(ids) == len(set(ids)), "duplicate ids across pages"
for pid in carol_orig:
    assert pid in ids, f"carol orig {pid} missing from feed walk"
assert bob_post not in ids
# user_posts: Carol's own list mixes her originals with her
# reposts of private Bob — same walk, same guarantees.
for i in range(25):
    mkpost_row(1793, repost_of_id=bob_post)
s = db()
try:
    expected = s.query(models.Post).filter_by(
        user_id=1793, is_deleted=False, repost_of_id=None).count()
finally:
    s.close()


def walk_user_posts(headers, uid):
    out, cur, pages = [], 0, []
    while True:
        r = c.get(f"/users/{uid}/posts" +
                  (f"?cursor={cur}" if cur else ""), headers=headers)
        assert r.status_code == 200, r.text
        j = r.json()
        pages.append(len(j["posts"]))
        out.extend(p["id"] for p in j["posts"])
        cur = j["next_cursor"]
        if cur is None:
            break
        assert j["posts"], "empty user-posts page with cursor"
    return out, pages


uids, upages = walk_user_posts(ALICE, 1793)
assert all(n == 20 for n in upages[:-1]), upages
assert all(n > 0 for n in upages), upages
assert len(uids) == expected, (len(uids), expected)
assert len(uids) == len(set(uids))
for pid in carol_orig:
    assert pid in uids
# hashtag feed: 25 posts, one tag — two pages, 20 + 5.
for i in range(25):
    mkpost_row(1793, caption=f"cursor tag {i}",
               hashtags="cursor179")
r = c.post("/hashtags/cursor179/follow", headers=FRANK)
assert r.status_code == 200, r.text
r = c.get("/feed/hashtags", headers=FRANK)
assert r.status_code == 200, r.text
assert len(r.json()["posts"]) == 20, r.json()
assert r.json()["next_cursor"] is not None
r = c.get(f"/feed/hashtags?cursor={r.json()['next_cursor']}",
          headers=FRANK)
assert r.status_code == 200, r.text
assert len(r.json()["posts"]) == 5, r.json()
assert r.json()["next_cursor"] is None
assert set_private(BOB, False) is False
print("11. M5 cursor: full pages, no empty-page gaps OK")

# 12. M4 rate limits: small test-only budgets prove the wiring
# (production budgets stay generous — 600/240 per hour).
_orig = dict(main_mod.RATE_LIMITS)
try:
    ratelimit.reset()
    main_mod.RATE_LIMITS["feed"] = (3, 3600)
    for _ in range(3):
        r = c.get("/feed", headers=FRANK)
        assert r.status_code == 200, r.text
    r = c.get("/feed", headers=FRANK)
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    ratelimit.reset()
    main_mod.RATE_LIMITS["saved"] = (2, 3600)
    for _ in range(2):
        r = c.get("/me/saved", headers=FRANK)
        assert r.status_code == 200, r.text
    r = c.get("/me/shared", headers=FRANK)
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    ratelimit.reset()
    main_mod.RATE_LIMITS["post_read"] = (2, 3600)
    for _ in range(2):
        r = c.get(f"/posts/{bob_post}", headers=FRANK)
        assert r.status_code == 200, r.text
    r = c.get(f"/posts/{bob_post}/comments", headers=FRANK)
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    ratelimit.reset()
    main_mod.RATE_LIMITS["stories"] = (1, 3600)
    r = c.get("/stories", headers=FRANK)
    assert r.status_code == 200, r.text
    r = c.get("/stories", headers=FRANK)
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    ratelimit.reset()
    main_mod.RATE_LIMITS["highlight_read"] = (1, 3600)
    r = c.get("/highlights/user/1792", headers=FRANK)
    assert r.status_code == 200, r.text
    r = c.get(f"/highlights/{hl_id}", headers=FRANK)
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    ratelimit.reset()
    main_mod.RATE_LIMITS["user_posts"] = (1, 3600)
    r = c.get("/users/1792/posts", headers=FRANK)
    assert r.status_code == 200, r.text
    r = c.get("/users/1792/posts", headers=FRANK)
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
finally:
    main_mod.RATE_LIMITS.clear()
    main_mod.RATE_LIMITS.update(_orig)
    ratelimit.reset()
# Budgets restored: the same calls work again.
r = c.get("/feed", headers=FRANK)
assert r.status_code == 200, r.text
r = c.get("/me/saved", headers=FRANK)
assert r.status_code == 200, r.text
r = c.get(f"/posts/{bob_post}", headers=FRANK)
assert r.status_code == 200, r.text
print("12. M4 rate buckets 429 with Retry-After, restore works OK")

# 13. Client markers, version, routes, backup tables, health.
assert HTML.count("?v=210") == 10, HTML.count("?v=210")
assert "?v=17" + "8" not in HTML
assert "/?v=210" in BOT and "/?v=17" + "8" not in BOT
assert "app.js?v=210" in HTML and "style.css?v=210" in HTML
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 196, len(paths)
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
b = r.json()
assert len(b["tables"]) == 55, len(b["tables"])
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
r = c.get("/health")
assert r.status_code == 200, r.text
h = c.get("/admin/health", headers=ADMIN).json()
assert h["version"] == 210, h
print("13. version + routes + backup + health OK")

print("PHASE 179 OK")
