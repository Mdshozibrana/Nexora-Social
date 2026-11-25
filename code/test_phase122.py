"""Phase-122 tests: Trending page.

Server: GET /trending/posts ranks by recent engagement velocity —
    score = (3*likes_7d + 5*comments_7d + 1*views_7d) / (1 + age_days)
  where the _7d counts cover only engagement from the last 7 days
  and age_days is the post's age in days. Only score > 0 trends;
  ties break by newer post id; top 20. Each card also carries
  trend_24h (raw engagement in the last 24h) and trend_7d.
  GET /trending/hashtags returns the most-used tags on posts from
  the last 7 days, most-used first.
Rules: blocked authors' posts hidden, deleted posts excluded,
repost rows never appear as their own entry (a reposted post trends
once, as its original), video posts trend in the same list, no
points are paid for trending views, and the feed order / post
counts are unchanged.
Client: the Trending view + sidebar entry, hashtag chips that reuse
searchTag, ranked postCards with a "#N · 🔥 M in 24h" rank line,
empty state, ?v=177, Nexa manual sentence.
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
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase122.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, auth_date=None):
    return {"X-Init-Data": make_init_data(
        {"id": uid, "first_name": name}, auth_date)}


UID = {"A": 881, "B": 882, "C": 883, "D": 884, "E": 885, "ADMIN": 999}
NOW = datetime.utcnow()


def post_as(c, uid, name, **body):
    r = c.post("/posts", json=body, headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()


def trending_posts(c, uid, name):
    r = c.get("/trending/posts", headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()["posts"]


def trending_tags(c, uid, name):
    r = c.get("/trending/hashtags", headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()["hashtags"]


def feed(c, uid, name, tab="explore", type_=""):
    r = c.get(f"/feed?tab={tab}" + (f"&type={type_}" if type_ else ""),
              headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()["posts"]


def seed_engagement(post_id, age_days, likes=0, comments=0, views=0,
                    like_age_h=1, comment_age_h=1, view_age_h=1):
    """Backdate the post, then insert Like/Comment/PostView rows with
    the given ages (hours ago) and mirror the denormalised counts so
    the card numbers match the tables."""
    db = SessionLocal()
    p = db.get(models.Post, post_id)
    p.created_at = NOW - timedelta(days=age_days)
    p.like_count = likes
    p.comment_count = comments
    db.commit()
    for i in range(likes):
        db.add(models.Like(post_id=post_id, user_id=9000 + i,
                           created_at=NOW - timedelta(hours=like_age_h)))
    for i in range(comments):
        db.add(models.Comment(post_id=post_id, user_id=9100 + i,
                              text="c%d" % i,
                              created_at=NOW - timedelta(hours=comment_age_h)))
    for i in range(views):
        db.add(models.PostView(post_id=post_id, user_id=9200 + i,
                               created_at=NOW - timedelta(hours=view_age_h)))
    db.commit()
    db.close()


with TestClient(app) as c:
    for name, uid in UID.items():
        r = c.post("/auth", json={"initData": H(uid, name)["X-Init-Data"]})
        assert r.status_code == 200, name

    # Empty state first: no post has any engagement yet, so nothing
    # trends — but the first /auth already created the official
    # account's welcome post ("... #nexora"), so the hashtag list
    # starts with that one tag, not empty.
    assert trending_posts(c, UID["A"], "A") == []
    assert trending_tags(c, UID["A"], "A") == [
        {"tag": "nexora", "count": 1}]
    print("trending: empty state OK")

    # --- Seed four posts with known counts and ages ---
    # p_new (1h old):  3 likes + 1 comment + 5 views, all in the
    #   last hour  -> (9+5+5) / 1.04  = 18.27
    # p_old (6d old): 10 likes + 5 comments + 20 views, all in the
    #   last hour  -> (30+25+20) / 7   = 10.71
    # p_mid (3d old):  5 likes 2 days ago -> 15 / 4 = 3.75
    # p_stale (2d old): engagement 8 days ago (outside the 7d
    #   window) -> score 0, must not trend at all.
    p_new = post_as(c, UID["A"], "A", type="text",
                    caption="fresh and hot #nexora #fun")
    p_old = post_as(c, UID["B"], "B", type="text",
                    caption="old but loved #nexora")
    p_mid = post_as(c, UID["C"], "C", type="text",
                    caption="steady #fun")
    p_stale = post_as(c, UID["D"], "D", type="text",
                       caption="yesterday's news #nexora #stale")
    seed_engagement(p_new["id"], 0.04, likes=3, comments=1, views=5)
    seed_engagement(p_old["id"], 6, likes=10, comments=5, views=20)
    seed_engagement(p_mid["id"], 3, likes=5, like_age_h=48)
    seed_engagement(p_stale["id"], 2, likes=9, comments=4, views=30,
                    like_age_h=8 * 24, comment_age_h=8 * 24,
                    view_age_h=8 * 24)

    posts = trending_posts(c, UID["A"], "A")
    ids = [p["id"] for p in posts]
    assert ids == [p_new["id"], p_old["id"], p_mid["id"]], ids
    assert p_stale["id"] not in ids
    # The ranking signal rides on each card.
    by_id = {p["id"]: p for p in posts}
    assert by_id[p_new["id"]]["trend_24h"] == 9, by_id[p_new["id"]]
    assert by_id[p_new["id"]]["trend_7d"] == 9
    assert abs(by_id[p_new["id"]]["trend_score"] - 18.27) < 0.05
    assert by_id[p_old["id"]]["trend_24h"] == 35
    assert abs(by_id[p_old["id"]]["trend_score"] - 10.71) < 0.05
    assert by_id[p_mid["id"]]["trend_24h"] == 0
    assert by_id[p_mid["id"]]["trend_7d"] == 5
    assert abs(by_id[p_mid["id"]]["trend_score"] - 3.75) < 0.05
    # Card fields are the real post (likes/comments/views match).
    assert by_id[p_old["id"]]["like_count"] == 10
    assert by_id[p_old["id"]]["comment_count"] == 5
    assert by_id[p_old["id"]]["views"] == 20
    print("trending: velocity ranking (18.27 > 10.71 > 3.75, stale out) OK")

    # Hashtags: last-7-day posts only, most-used first.
    # #nexora: welcome post + p_new + p_old + p_stale = 4 (p_stale's
    #   engagement is 8 days old, but the POST is 2 days old, so its
    #   tag still counts); #fun: p_new + p_mid = 2; #stale: 1.
    tags = trending_tags(c, UID["A"], "A")
    assert tags == [{"tag": "nexora", "count": 4},
                    {"tag": "fun", "count": 2},
                    {"tag": "stale", "count": 1}], tags
    print("trending: hashtag counts in order OK")

    # A video post trends in the same list (no separate video list).
    p_vid = post_as(c, UID["A"], "A", type="video",
                    media_file_id="fakevid1", caption="reel time #fun")
    seed_engagement(p_vid["id"], 0.02, likes=2, views=4)
    posts = trending_posts(c, UID["A"], "A")
    vid = next(p for p in posts if p["id"] == p_vid["id"])
    assert vid["type"] == "video"
    assert abs(vid["trend_score"] - (6 + 4) / 1.02) < 0.05
    print("trending: video posts trend in the same list OK")

    # A repost never appears as its own entry: B reposts p_new.
    r = c.post(f"/posts/{p_new['id']}/repost", headers=H(UID["B"], "B"))
    assert r.status_code == 200, r.text
    posts = trending_posts(c, UID["A"], "A")
    assert [p["id"] for p in posts].count(p_new["id"]) == 1, posts
    assert len(posts) == 4, posts
    print("trending: repost trends once, as its original OK")

    # Deleted post drops out.
    r = c.delete(f"/posts/{p_mid['id']}", headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    assert p_mid["id"] not in [p["id"] for p in trending_posts(c, UID["A"], "A")]
    print("trending: deleted post excluded OK")

    # Blocked author's posts are hidden from the blocker — and only
    # from them. E posts hot, A blocks E.
    p_e = post_as(c, UID["E"], "E", type="text",
                  caption="blocked but hot #nexora")
    seed_engagement(p_e["id"], 0.01, likes=8, views=8)
    assert p_e["id"] in [p["id"] for p in trending_posts(c, UID["B"], "B")]
    r = c.post(f"/users/{UID['E']}/block", headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    assert p_e["id"] not in [p["id"] for p in trending_posts(c, UID["A"], "A")]
    assert p_e["id"] in [p["id"] for p in trending_posts(c, UID["B"], "B")]
    tags_a = trending_tags(c, UID["A"], "A")
    # #nexora for A: welcome + p_new + p_old + p_stale = 4 (E's post
    #   no longer counted for A); for B it would be 5.
    assert {"tag": "nexora", "count": 4} in tags_a, tags_a
    assert {"tag": "nexora", "count": 5} in trending_tags(c, UID["B"], "B")
    print("trending: blocked author hidden (posts + hashtag counts) OK")

    # No points for trending views: opening the page pays nothing.
    before = c.get("/me/monetization", headers=H(UID["A"], "A")).json()
    trending_posts(c, UID["A"], "A")
    after = c.get("/me/monetization", headers=H(UID["A"], "A")).json()
    assert before == after
    print("trending: no points for trending views OK")

    # Neighbouring behaviour unchanged: the feed still lists rows
    # newest-first — the repost row makes p_new appear twice (once
    # as B's repost, once as A's own post: Phase 118 behaviour),
    # the video stays off the main feed (Phase 35), the deleted
    # post and the blocked author's post stay out.
    feed_ids = [p["id"] for p in feed(c, UID["A"], "A")]
    assert feed_ids == [p_new["id"], p_stale["id"], p_old["id"],
                        p_new["id"], 1], feed_ids  # 1 = official welcome
    prof_a = c.get(f"/users/{UID['A']}", headers=H(UID["A"], "A")).json()
    assert prof_a["posts"] == 2, prof_a  # p_new + p_vid
    prof_b = c.get(f"/users/{UID['B']}", headers=H(UID["B"], "B")).json()
    assert prof_b["posts"] == 1, prof_b  # repost never counts
    print("neighbouring: feed order + post counts unchanged OK")

    # Client markers.
    html = open("webapp/index.html").read()
    js = open("webapp/app.js").read()
    css = open("webapp/style.css").read()
    main = open("app/main.py").read()
    assert html.count("?v=177") == 10, html.count("?v=177")
    assert "?v=121" not in html
    for bit in ('id="view-trending"', 'id="trend-tags"',
                'id="trend-list"', 'id="trend-empty"',
                'id="trend-refresh"', 'data-go="trending"',
                "No trending posts yet", "What's hot right now"):
        assert bit in html, bit
    # The 7-tab bottom bar is untouched.
    for bit in ("nav-feed", "nav-videos", "nav-design", "nav-games",
                "nav-tasks", "nav-ranks", "nav-me"):
        assert 'id="%s"' % bit in html, bit
    assert html.count('class="gb-item" data-go="videos"') == 1
    for bit in ("loadTrending", "/trending/posts", "/trending/hashtags",
                "trend-rank", "in 24h", "this week", "postCard(p)",
                "searchTag(h.tag)", "trend-refresh"):
        assert bit in js, bit
    for bit in (".trend-tags", ".trend-rank", ".trend-item"):
        assert bit in css, bit
    # Nexa's manual knows about Trending.
    assert "TRENDING: the sidebar has a Trending page" in main
    # Earlier phases intact.
    for bit in ("repost-banner", "Replying to", "syncObsDial",
                "wireObsQuickActions", "maybeLoadMoreDesigns",
                "loadRelatedDesigns", "loadMyQr", "openPhotoViewer"):
        assert bit in js, bit
    print("client: view + sidebar + chips + rank line + ?v=177 + Nexa OK")

print("PHASE 122 OK")
