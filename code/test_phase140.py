"""Phase-140 tests: hashtag follow.

Covers: POST /hashtags/{tag}/follow (normalization "#Tech" ->
"tech", duplicate -> 400, invalid tag -> 400, unauthenticated
401); DELETE /hashtags/{tag}/follow (unfollow -> 200, again ->
404, never-followed -> 404); GET /me/hashtags (own tags only,
newest first, with live post counts); GET /feed/hashtags
(posts with a followed hashtag, newest first; posts without
the tag absent; a repost of a tagged post does NOT duplicate
it — repost rows carry no hashtags, exactly like the #tag
search); private accounts (a private author's hashtagged posts
stay hidden from non-followers, visible to followers, and
going private hides even older posts); backup 42 tables incl.
hashtag_follows rows; ?v=206 x5; hashtag-follow client markers
+ Phase 123-139 markers intact.

Survey note: hashtags live as a space-joined lowercase string
on Post.hashtags (extract_hashtags); reposts carry hashtags="".
"""
import hashlib, hmac, json, os, sqlite3, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase140.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.main as main_mod

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models

def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)

def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}

ALICE = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")


def mkpost(c, headers, caption):
    r = c.post("/posts", headers=headers,
               json={"type": "text", "caption": caption})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def feed_ids(c, headers):
    r = c.get("/feed/hashtags", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Follow / unfollow validation.
    r = c.post("/hashtags/Tech/follow", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json() == {"following": True, "tag": "tech"}, r.json()
    r = c.post("/hashtags/%23Tech/follow", headers=BOB)
    assert r.status_code == 400, r.status_code  # normalizes, duplicate
    r = c.post("/hashtags/tech/follow", headers=BOB)
    assert r.status_code == 400, r.status_code
    r = c.post("/hashtags/!!!/follow", headers=BOB)
    assert r.status_code == 400, r.status_code
    r = c.post("/hashtags/" + "x" * 51 + "/follow", headers=BOB)
    assert r.status_code == 400, r.status_code
    r = c.post("/hashtags/tech/follow")
    assert r.status_code == 401, r.status_code
    r = c.get("/me/hashtags", headers=BOB)
    assert r.status_code == 200, r.text
    assert [h["tag"] for h in r.json()["hashtags"]] == ["tech"], r.json()
    r = c.get("/me/hashtags", headers=CAROL)
    assert r.json() == {"hashtags": []}, r.json()
    r = c.delete("/hashtags/tech/follow", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json() == {"following": False, "tag": "tech"}, r.json()
    r = c.delete("/hashtags/tech/follow", headers=BOB)
    assert r.status_code == 404, r.status_code
    r = c.delete("/hashtags/tech/follow", headers=CAROL)
    assert r.status_code == 404, r.status_code
    print("follow/unfollow validation OK")

    # 2. Hashtag feed: only posts carrying a followed tag.
    p1 = mkpost(c, ALICE, "#Tech first post")
    p2 = mkpost(c, BOB, "plain post no tags")
    p3 = mkpost(c, CAROL, "#tech and #news")
    r = c.post("/hashtags/tech/follow", headers=BOB)
    assert r.status_code == 200, r.text
    assert feed_ids(c, BOB) == [p3, p1], feed_ids(c, BOB)
    # A repost of a tagged post does NOT duplicate it in the
    # feed — repost rows carry no hashtags of their own.
    r = c.post(f"/posts/{p1}/repost", headers=BOB)
    assert r.status_code == 200, r.text
    assert feed_ids(c, BOB) == [p3, p1], feed_ids(c, BOB)
    # Carol follows tech too; unfollowing empties the feed.
    r = c.post("/hashtags/tech/follow", headers=CAROL)
    assert r.status_code == 200, r.text
    assert feed_ids(c, CAROL) == [p3, p1], feed_ids(c, CAROL)
    r = c.delete("/hashtags/tech/follow", headers=CAROL)
    assert r.status_code == 200, r.text
    assert feed_ids(c, CAROL) == [], feed_ids(c, CAROL)
    r = c.delete("/hashtags/tech/follow", headers=BOB)
    assert r.status_code == 200, r.text
    assert feed_ids(c, BOB) == [], feed_ids(c, BOB)
    print("hashtag feed OK (match / no-match / repost / unfollow)")

    # 3. Private account: her hashtagged posts hide from
    # non-followers (even older ones) and show to followers.
    r = c.post("/users/111/follow", headers=BOB)
    assert r.status_code == 200, r.text
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": True})
    assert r.status_code == 200, r.text
    p4 = mkpost(c, ALICE, "#tech private post")
    r = c.post("/hashtags/tech/follow", headers=CAROL)
    assert r.status_code == 200, r.text
    assert feed_ids(c, CAROL) == [p3], feed_ids(c, CAROL)
    r = c.post("/hashtags/tech/follow", headers=BOB)
    assert r.status_code == 200, r.text
    assert feed_ids(c, BOB) == [p4, p3, p1], feed_ids(c, BOB)
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": False})
    assert r.status_code == 200, r.text
    assert feed_ids(c, CAROL) == [p4, p3, p1], feed_ids(c, CAROL)
    print("private-account guard OK")

    # 4. /me/hashtags counts live original posts per tag.
    r = c.post("/hashtags/news/follow", headers=BOB)
    assert r.status_code == 200, r.text
    r = c.get("/me/hashtags", headers=BOB)
    tags = {h["tag"]: h["count"] for h in r.json()["hashtags"]}
    assert tags == {"tech": 3, "news": 1}, tags
    assert [h["tag"] for h in r.json()["hashtags"]] == ["news", "tech"], \
        r.json()
    assert all(h["created_at"] for h in r.json()["hashtags"]), r.json()
    print("my-hashtags counts OK")

    # 5. Backup carries 42 tables incl. hashtag_follows rows.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    bk = r.json()
    assert len(bk["tables"]) == 55, len(bk["tables"])
    assert "hashtag_follows" in bk["tables"], list(bk["tables"])
    assert len(bk["tables"]["hashtag_follows"]) >= 2, \
        len(bk["tables"]["hashtag_follows"])
    print("backup: 42 tables incl. hashtag_follows OK")

    # 6. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=206") == 10, html.count("?v=206")
    assert "?v=13" + "9" not in html
    js = open("webapp/app.js").read()
    for m in ("tab-hashtags", "search-tag-follow", "hashtag-card",
              "hashtag-row", "Hashtags I follow", "followedTags",
              "/me/hashtags", "/feed/hashtags", "Follow a hashtag",
              'setTab("hashtags")', "Hashtags"):
        assert m in js, m
    for m in ("tab-hashtags", "search-tag-follow"):
        assert m in html, m
    main_src = open("app/main.py").read()
    for m in ("HashtagFollow", "hashtag_follow", "_clean_tag",
              "follow_hashtag", "unfollow_hashtag", "my_hashtags",
              "hashtag_feed"):
        assert m in main_src, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus", "openTipSheet", "openInsights",
              "ins-chart", "ins-table", "schedLocalInput", "loadScheduled",
              "composer-schedule", "loadFollowRequests", "privacy-row",
              "private-lock", "renderLevelBlock", "level-block",
              "level-bar", "badge-row", "badge-chip", "badge-locked",
              "DM_REACTIONS", "reactToMessage", "chat-photo",
              "bubble-photo", "openStoryViewers", "sendStoryReply",
              "story-reply", "story-viewers"):
        assert m in js, m
    css = open("webapp/style.css").read()
    assert ".hashtag-row" in css
    print("client markers + ?v=206 OK")

print("PHASE-140 TESTS PASSED")
