"""Phase-118 tests: Repost + Comment Reply.

Repost: a post shared to your own feed (toggle). The card shows
the ORIGINAL (id/likes/comments/views belong to it) with a
"🔁 X reposted" banner; reposting a repost resolves to the
original; your own post cannot be reposted; a video repost
belongs on the Videos tab, not the main feed; reposts never
count toward post totals; deleting the original takes its
reposts with it.
Comment Reply: replies nest one level under their top comment;
a reply to a reply answers the top comment; the parent author
is notified.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase118.db"

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


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


UID = {"A": 881, "B": 882, "C": 883, "D": 884, "ADMIN": 999}


def post_as(c, uid, name, **body):
    r = c.post("/posts", json=body, headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()


def feed(c, uid, name, tab="explore", type_=""):
    r = c.get(f"/feed?tab={tab}" + (f"&type={type_}" if type_ else ""),
              headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()["posts"]


def profile_posts(c, uid, name, target):
    r = c.get(f"/users/{target}/posts", headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()["posts"]


with TestClient(app) as c:
    for name, uid in UID.items():
        r = c.post("/auth", json={"initData": H(uid, name)["X-Init-Data"]})
        assert r.status_code == 200, name

    # A posts; B reposts it.
    p1 = post_as(c, UID["A"], "A", type="text",
                 caption="hello world #test")
    r = c.post(f"/posts/{p1['id']}/repost", headers=H(UID["B"], "B"))
    assert r.status_code == 200 and r.json() == {
        "reposted": True, "repost_count": 1}, r.text
    cards = feed(c, UID["B"], "B")
    card = next(p for p in cards if p["id"] == p1["id"])
    assert card["reposted"] is True, card
    assert card["reposted_by_name"] == "B", card
    assert card["reposted_by_me"] is True, card
    assert card["repost_count"] == 1 and card["caption"] == "hello world #test"
    assert card["author_id"] == UID["A"]
    card_a = next(p for p in feed(c, UID["A"], "A") if p["id"] == p1["id"])
    assert card_a["reposted_by_me"] is False
    print("repost: card shows the original + reposter OK")

    # C follows B: the repost reaches C's Following feed.
    r = c.post(f"/users/{UID['B']}/follow", headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    assert any(p["id"] == p1["id"] and p["reposted"]
               for p in feed(c, UID["C"], "C", tab="following"))
    print("repost: reaches the reposter's followers OK")

    # Reposts never count as posts: B's totals stay 0, A's stay 1.
    assert len(profile_posts(c, UID["B"], "B", UID["B"])) == 1
    assert profile_posts(c, UID["B"], "B", UID["B"])[0]["reposted"] is True
    prof_b = c.get(f"/users/{UID['B']}", headers=H(UID["B"], "B")).json()
    assert prof_b["posts"] == 0, prof_b
    prof_a = c.get(f"/users/{UID['A']}", headers=H(UID["A"], "A")).json()
    assert prof_a["posts"] == 1, prof_a
    mon_b = c.get("/me/monetization", headers=H(UID["B"], "B")).json()
    posts_check = next(x for x in mon_b["checks"] if x["key"] == "posts")
    assert posts_check["current"] == 0, mon_b
    print("repost: never counts toward post totals OK")

    # Toggle off: the repost is gone from the feed and the profile.
    r = c.post(f"/posts/{p1['id']}/repost", headers=H(UID["B"], "B"))
    assert r.json() == {"reposted": False, "repost_count": 0}, r.text
    assert not any(p["id"] == p1["id"] and p.get("reposted")
                   for p in feed(c, UID["B"], "B"))
    assert profile_posts(c, UID["B"], "B", UID["B"]) == []
    print("repost: toggle off removes it OK")

    # Reposting a repost resolves to the original.
    c.post(f"/posts/{p1['id']}/repost", headers=H(UID["B"], "B"))
    repost_row_id = profile_posts(c, UID["B"], "B", UID["B"])[0]["repost_id"]
    r = c.post(f"/posts/{repost_row_id}/repost", headers=H(UID["C"], "C"))
    assert r.json() == {"reposted": True, "repost_count": 2}, r.text
    print("repost: reposting a repost resolves to the original OK")

    # Your own post cannot be reposted.
    p2 = post_as(c, UID["B"], "B", type="text", caption="mine")
    assert c.post(f"/posts/{p2['id']}/repost",
                  headers=H(UID["B"], "B")).status_code == 400
    print("repost: own post rejected OK")

    # A video repost belongs on the Videos tab, not the main feed.
    p3 = post_as(c, UID["A"], "A", type="video", media_file_id="fake123")
    c.post(f"/posts/{p3['id']}/repost", headers=H(UID["B"], "B"))
    assert not any(p["id"] == p3["id"] for p in feed(c, UID["B"], "B"))
    assert any(p["id"] == p3["id"] and p["reposted"]
               for p in feed(c, UID["B"], "B", type_="video"))
    print("repost: video repost stays off the main feed OK")

    # Deleting the original takes its reposts with it.
    r = c.delete(f"/posts/{p1['id']}", headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    assert not any(p["id"] == p1["id"] for p in feed(c, UID["B"], "B"))
    assert not any(p["id"] == p1["id"]
                   for p in profile_posts(c, UID["B"], "B", UID["B"]))
    assert profile_posts(c, UID["C"], "C", UID["C"]) == []
    print("repost: deleting the original removes its reposts OK")

    # ---- Comment replies ----
    p4 = post_as(c, UID["A"], "A", type="text", caption="talk here")
    r = c.post(f"/posts/{p4['id']}/comments",
               json={"text": "nice post"}, headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    top = r.json()
    assert top["parent_id"] is None and top["reply_count"] == 0
    r = c.post(f"/posts/{p4['id']}/comments",
               json={"text": "agreed!", "parent_id": top["id"]},
               headers=H(UID["B"], "B"))
    assert r.status_code == 200, r.text
    reply_b = r.json()
    assert reply_b["parent_id"] == top["id"]
    # A reply to a reply answers the TOP comment instead.
    r = c.post(f"/posts/{p4['id']}/comments",
               json={"text": "me too", "parent_id": reply_b["id"]},
               headers=H(UID["D"], "D"))
    assert r.status_code == 200 and r.json()["parent_id"] == top["id"], r.text
    # A parent from another post is rejected.
    p5 = post_as(c, UID["A"], "A", type="text", caption="other post")
    r = c.post(f"/posts/{p5['id']}/comments",
               json={"text": "wrong place", "parent_id": top["id"]},
               headers=H(UID["B"], "B"))
    assert r.status_code == 400, r.text
    # The list nests the replies under their top comment.
    r = c.get(f"/posts/{p4['id']}/comments", headers=H(UID["A"], "A"))
    cmts = r.json()["comments"]
    assert len(cmts) == 1, cmts
    assert cmts[0]["reply_count"] == 2, cmts[0]
    assert [x["text"] for x in cmts[0]["replies"]] == ["agreed!", "me too"]
    assert cmts[0]["replies"][0]["parent_id"] == top["id"]
    post4 = next(p for p in feed(c, UID["A"], "A") if p["id"] == p4["id"])
    assert post4["comment_count"] == 3, post4
    # The parent author (C) got a reply notification; A got comments.
    db = SessionLocal()
    assert db.query(models.Notification).filter_by(
        user_id=UID["C"], type="reply").count() >= 1
    assert db.query(models.Notification).filter_by(
        user_id=UID["A"], type="comment").count() >= 1
    db.close()
    print("replies: nest one level, notify the parent author OK")

    # Client markers + earlier phases intact.
    html = c.get("/webapp/").text
    js = c.get("/webapp/app.js").text
    css = c.get("/webapp/style.css").text
    for bit in ("reposted_by_name", "Reposted to your feed",
                "Replying to", "comment-replies", "repost-banner",
                "reel-repost"):
        assert bit in js, bit
    for bit in (".repost-banner", ".comment-replies", ".reply-chip"):
        assert bit in css, bit
    for asset in ("style.css?v=118", "app.js?v=118", "games.js?v=118"):
        assert asset in html, asset
    for bit in ("maybeLoadMoreDesigns", "loadRelatedDesigns",
                "loadMyQr", "showTaskAd", "openPhotoViewer", "pvZoomIn"):
        assert bit in js or bit in css, bit
    print("client: repost + reply UI markers OK")

print("PHASE 118 OK")
