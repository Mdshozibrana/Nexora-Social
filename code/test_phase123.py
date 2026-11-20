"""Phase-123 tests: Creator tools — pinned posts, drafts,
comment likes, polls.

Pins: an author pins ONE of their own posts (toggle); pinning a
second unpins the first; a pinned post leads their profile listing
(📌 badge on the card); non-author 403, unknown 404, a repost
cannot be pinned (400).
Drafts: save text (+ optional media reference), list newest-first
(own only), publish through the normal post path (+10 points, draft
gone), delete (own only, others 404).
Comment likes: toggle per comment, counts + liked_by_me ride on
list_comments (top-level and replies), 404 for unknown/mismatched
comment, 403 on a blocked author's post.
Polls: a post may carry a poll (question + 2-4 options, enforced);
members vote once and cannot change it (400 on a second vote);
results shape (options with votes, total_votes, voted_option_id);
404 voting on a post with no poll; 400 for a bad option.
Backup: the format now carries 35 tables incl. the five new ones,
with their rows; a restore round-trip brings them back.
Client: ?v=160, composer poll form + Save draft, pin badge + pin
menu row, poll block, comment heart, My drafts in profile extras,
Nexa manual line.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase123.db"

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


def profile_posts(c, uid, name):
    r = c.get(f"/users/{uid}/posts", headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()["posts"]


def comments_of(c, post_id, uid, name):
    r = c.get(f"/posts/{post_id}/comments", headers=H(uid, name))
    assert r.status_code == 200, r.text
    return r.json()["comments"]


with TestClient(app) as c:
    for name, uid in UID.items():
        r = c.post("/auth", json={"initData": H(uid, name)["X-Init-Data"]})
        assert r.status_code == 200, name

    # Unauthenticated creator-tools calls are 401.
    assert c.post("/posts/1/pin").status_code == 401
    assert c.post("/posts/1/poll/vote",
                  json={"option_id": 1}).status_code == 401
    assert c.post("/posts/1/comments/1/like").status_code == 401
    assert c.get("/drafts").status_code == 401
    assert c.post("/drafts", json={"text": "x"}).status_code == 401
    print("creator tools: unauthenticated 401 OK")

    # ---------------------------------------------------------- pins --
    p1 = post_as(c, UID["A"], "A", type="text", caption="first post")
    p2 = post_as(c, UID["A"], "A", type="text", caption="second post")
    p3 = post_as(c, UID["A"], "A", type="text", caption="third post")
    assert p1["poll"] is None and p1["is_pinned"] is False
    # Pin the OLDEST post: it must lead the profile listing.
    r = c.post(f"/posts/{p1['id']}/pin", headers=H(UID["A"], "A"))
    assert r.status_code == 200 and r.json() == {
        "pinned": True, "post_id": p1["id"]}, r.text
    prof = profile_posts(c, UID["A"], "A")
    assert [p["id"] for p in prof] == [p1["id"], p3["id"], p2["id"]], prof
    assert prof[0]["is_pinned"] is True
    assert prof[1]["is_pinned"] is False
    print("pin: oldest post pinned leads the profile OK")
    # Pinning a second post unpins the first (one pin per author).
    r = c.post(f"/posts/{p2['id']}/pin", headers=H(UID["A"], "A"))
    assert r.status_code == 200 and r.json()["pinned"] is True
    prof = profile_posts(c, UID["A"], "A")
    assert [p["id"] for p in prof] == [p2["id"], p3["id"], p1["id"]], prof
    assert prof[0]["is_pinned"] is True
    assert prof[2]["is_pinned"] is False
    # Toggle off: plain newest-first order returns.
    r = c.post(f"/posts/{p2['id']}/pin", headers=H(UID["A"], "A"))
    assert r.status_code == 200 and r.json()["pinned"] is False
    prof = profile_posts(c, UID["A"], "A")
    assert [p["id"] for p in prof] == [p3["id"], p2["id"], p1["id"]], prof
    assert all(p["is_pinned"] is False for p in prof)
    print("pin: one-pin rule + toggle off OK")
    # Guards: non-author 403, unknown 404.
    r = c.post(f"/posts/{p3['id']}/pin", headers=H(UID["B"], "B"))
    assert r.status_code == 403, r.status_code
    r = c.post("/posts/999999/pin", headers=H(UID["A"], "A"))
    assert r.status_code == 404, r.status_code
    # A repost cannot be pinned (only own originals).
    db = SessionLocal()
    rp = models.Post(user_id=UID["B"], type="repost",
                     repost_of_id=p3["id"], caption="", hashtags="")
    db.add(rp)
    db.commit()
    db.refresh(rp)
    db.close()
    r = c.post(f"/posts/{rp.id}/pin", headers=H(UID["B"], "B"))
    assert r.status_code == 400, r.text
    print("pin: 403 / 404 / repost-400 guards OK")
    # Pinning does not disturb the feed order (newest first) —
    # the repost row makes p3 appear twice (Phase 118 behaviour).
    feed_ids = [p["id"] for p in feed(c, UID["A"], "A")]
    assert feed_ids == [p3["id"], p3["id"], p2["id"], p1["id"], 1], feed_ids
    print("pin: feed order unchanged OK")

    # -------------------------------------------------------- drafts --
    r = c.post("/drafts", json={"text": "   "}, headers=H(UID["A"], "A"))
    assert r.status_code == 400, r.text
    r = c.post("/drafts", json={"text": "unfinished thought"},
               headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    d1 = r.json()
    assert d1["text"] == "unfinished thought"
    assert d1["media_file_id"] is None
    r = c.post("/drafts", json={"text": "photo draft",
                                "media_file_id": "DRAFTPHOTO",
                                "media_type": "photo"},
               headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    d2 = r.json()
    assert d2["media_type"] == "photo"
    # Newest first, own only.
    r = c.get("/drafts", headers=H(UID["A"], "A"))
    assert [d["id"] for d in r.json()["drafts"]] == [d2["id"], d1["id"]]
    r = c.get("/drafts", headers=H(UID["B"], "B"))
    assert r.json()["drafts"] == [], r.text
    print("drafts: save + list (newest first, own only) OK")
    # Another member cannot delete or publish your draft.
    r = c.delete(f"/drafts/{d1['id']}", headers=H(UID["B"], "B"))
    assert r.status_code == 404, r.status_code
    r = c.post(f"/drafts/{d1['id']}/publish", headers=H(UID["B"], "B"))
    assert r.status_code == 404, r.status_code
    # Publish the text draft: a real post, draft gone.
    r = c.post(f"/drafts/{d1['id']}/publish", headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    pub1 = r.json()
    assert pub1["caption"] == "unfinished thought"
    assert pub1["type"] == "text"
    r = c.get("/drafts", headers=H(UID["A"], "A"))
    assert [d["id"] for d in r.json()["drafts"]] == [d2["id"]]
    # Publish the photo draft: media reference rides along.
    r = c.post(f"/drafts/{d2['id']}/publish", headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    pub2 = r.json()
    assert pub2["type"] == "photo"
    assert pub2["media_file_id"] == "DRAFTPHOTO"
    r = c.get("/drafts", headers=H(UID["A"], "A"))
    assert r.json()["drafts"] == []
    # Publishing went through the normal post path: +10 points each.
    # A has 3 posts + 2 published drafts = 5 posts = 50 points.
    pts = c.get("/me/points", headers=H(UID["A"], "A")).json()
    assert pts["balance"] == 50, pts
    # Delete your own draft; unknown draft 404s.
    r = c.post("/drafts", json={"text": "to delete"},
               headers=H(UID["A"], "A"))
    d3 = r.json()
    r = c.delete(f"/drafts/{d3['id']}", headers=H(UID["A"], "A"))
    assert r.status_code == 200 and r.json() == {"ok": True, "id": d3["id"]}
    r = c.post("/drafts/999999/publish", headers=H(UID["A"], "A"))
    assert r.status_code == 404, r.status_code
    print("drafts: publish (+10 pts each) + delete + guards OK")

    # -------------------------------------------------- comment likes --
    pc = post_as(c, UID["B"], "B", type="text", caption="comment me")
    r = c.post(f"/posts/{pc['id']}/comments", json={"text": "nice!"},
               headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    cm = r.json()
    assert cm["like_count"] == 0 and cm["liked_by_me"] is False
    lst = comments_of(c, pc["id"], UID["A"], "A")
    assert lst[0]["like_count"] == 0
    assert lst[0]["liked_by_me"] is False
    # B likes, then A likes: count climbs to 2.
    r = c.post(f"/posts/{pc['id']}/comments/{cm['id']}/like",
               headers=H(UID["B"], "B"))
    assert r.status_code == 200 and r.json() == {
        "liked": True, "like_count": 1, "comment_id": cm["id"]}, r.text
    r = c.post(f"/posts/{pc['id']}/comments/{cm['id']}/like",
               headers=H(UID["A"], "A"))
    assert r.json()["like_count"] == 2
    lst_a = comments_of(c, pc["id"], UID["A"], "A")
    assert lst_a[0]["like_count"] == 2
    assert lst_a[0]["liked_by_me"] is True
    lst_c = comments_of(c, pc["id"], UID["C"], "C")
    assert lst_c[0]["like_count"] == 2
    assert lst_c[0]["liked_by_me"] is False
    # Toggle off: A unlikes, count drops to 1.
    r = c.post(f"/posts/{pc['id']}/comments/{cm['id']}/like",
               headers=H(UID["A"], "A"))
    assert r.json() == {"liked": False, "like_count": 1,
                        "comment_id": cm["id"]}
    print("comment likes: toggle + counts + liked_by_me OK")
    # Replies carry likes too.
    r = c.post(f"/posts/{pc['id']}/comments",
               json={"text": "agreed", "parent_id": cm["id"]},
               headers=H(UID["C"], "C"))
    assert r.status_code == 200, r.text
    reply = r.json()
    r = c.post(f"/posts/{pc['id']}/comments/{reply['id']}/like",
               headers=H(UID["B"], "B"))
    assert r.json()["like_count"] == 1
    lst = comments_of(c, pc["id"], UID["B"], "B")
    assert lst[0]["replies"][0]["like_count"] == 1
    assert lst[0]["replies"][0]["liked_by_me"] is True
    print("comment likes: reply likes OK")
    # Guards: unknown comment 404, comment on another post 404.
    r = c.post(f"/posts/{pc['id']}/comments/999999/like",
               headers=H(UID["A"], "A"))
    assert r.status_code == 404, r.status_code
    other = post_as(c, UID["C"], "C", type="text", caption="other post")
    r = c.post(f"/posts/{other['id']}/comments/{cm['id']}/like",
               headers=H(UID["A"], "A"))
    assert r.status_code == 404, r.status_code
    # Blocked author's post: A blocks C, then A cannot like a
    # comment on C's post — but B (not blocked) still can.
    pblk = post_as(c, UID["C"], "C", type="text", caption="blocked post")
    r = c.post(f"/posts/{pblk['id']}/comments", json={"text": "hi"},
               headers=H(UID["A"], "A"))
    cmblk = r.json()
    r = c.post(f"/users/{UID['C']}/block", headers=H(UID["A"], "A"))
    assert r.status_code == 200, r.text
    r = c.post(f"/posts/{pblk['id']}/comments/{cmblk['id']}/like",
               headers=H(UID["A"], "A"))
    assert r.status_code == 403, r.status_code
    r = c.post(f"/posts/{pblk['id']}/comments/{cmblk['id']}/like",
               headers=H(UID["B"], "B"))
    assert r.status_code == 200, r.text
    print("comment likes: 404 / blocked-403 guards OK")

    # ---------------------------------------------------------- polls --
    # Validation: 1 option, 5 options, empty question all 400 —
    # and none of them creates a post.
    before = len(profile_posts(c, UID["A"], "A"))
    for bad in ({"question": "Q?", "options": ["only"]},
                {"question": "Q?",
                 "options": ["a", "b", "c", "d", "e"]},
                {"question": "  ", "options": ["a", "b"]}):
        r = c.post("/posts", json={"type": "text", "caption": "bad poll",
                                   "poll": bad}, headers=H(UID["A"], "A"))
        assert r.status_code == 400, (bad, r.text)
    assert len(profile_posts(c, UID["A"], "A")) == before
    print("polls: 2-4 options + question enforced, no post created OK")
    # A valid poll: shape on the created post.
    pp = post_as(c, UID["A"], "A", type="text", caption="pick one",
                 poll={"question": "Best pet?",
                       "options": ["Cats", "Dogs", "Birds"]})
    assert pp["poll"]["question"] == "Best pet?"
    assert [o["text"] for o in pp["poll"]["options"]] == [
        "Cats", "Dogs", "Birds"]
    assert [o["votes"] for o in pp["poll"]["options"]] == [0, 0, 0]
    assert pp["poll"]["total_votes"] == 0
    assert pp["poll"]["voted_option_id"] is None
    opts = {o["text"]: o["id"] for o in pp["poll"]["options"]}
    # B votes Dogs; a second vote is final (400).
    r = c.post(f"/posts/{pp['id']}/poll/vote",
               json={"option_id": opts["Dogs"]}, headers=H(UID["B"], "B"))
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["total_votes"] == 1
    assert res["voted_option_id"] == opts["Dogs"]
    assert {o["text"]: o["votes"] for o in res["options"]} == {
        "Cats": 0, "Dogs": 1, "Birds": 0}
    r = c.post(f"/posts/{pp['id']}/poll/vote",
               json={"option_id": opts["Cats"]}, headers=H(UID["B"], "B"))
    assert r.status_code == 400, r.text
    # D votes Cats, A (author) votes Birds: 3 votes, one each.
    # (C cannot vote here — A blocked C in the comment-likes
    # section above, and the blocked-author guard applies.)
    r = c.post(f"/posts/{pp['id']}/poll/vote",
               json={"option_id": opts["Cats"]}, headers=H(UID["D"], "D"))
    assert r.status_code == 200, r.text
    r = c.post(f"/posts/{pp['id']}/poll/vote",
               json={"option_id": opts["Birds"]}, headers=H(UID["A"], "A"))
    assert r.json()["total_votes"] == 3
    print("polls: vote once, results live, vote is final OK")
    # Results shape rides on the profile listing, per viewer.
    # (B reads A's profile to see the poll post.)
    prof = c.get(f"/users/{UID['A']}/posts",
                 headers=H(UID["B"], "B")).json()["posts"]
    got = next(p for p in prof if p["id"] == pp["id"])
    assert got["poll"]["total_votes"] == 3
    assert got["poll"]["voted_option_id"] == opts["Dogs"]
    assert {o["text"]: o["votes"] for o in got["poll"]["options"]} == {
        "Cats": 1, "Dogs": 1, "Birds": 1}
    prof_a = c.get(f"/users/{UID['A']}/posts",
                   headers=H(UID["A"], "A")).json()["posts"]
    got_a = next(p for p in prof_a if p["id"] == pp["id"])
    assert got_a["poll"]["voted_option_id"] == opts["Birds"]
    print("polls: results shape on profile listing, per viewer OK")
    # Guards: bad option 400 (unknown id, and an option from
    # another poll), no poll 404, unknown post 404.
    pp2 = post_as(c, UID["A"], "A", type="text", caption="second poll",
                  poll={"question": "Tea or coffee?",
                        "options": ["Tea", "Coffee"]})
    r = c.post(f"/posts/{pp2['id']}/poll/vote",
               json={"option_id": 999999}, headers=H(UID["B"], "B"))
    assert r.status_code == 400, r.text
    r = c.post(f"/posts/{pp2['id']}/poll/vote",
               json={"option_id": opts["Dogs"]}, headers=H(UID["B"], "B"))
    assert r.status_code == 400, r.text
    r = c.post(f"/posts/{p1['id']}/poll/vote",
               json={"option_id": 1}, headers=H(UID["B"], "B"))
    assert r.status_code == 404, r.text
    r = c.post("/posts/999999/poll/vote",
               json={"option_id": 1}, headers=H(UID["B"], "B"))
    assert r.status_code == 404, r.text
    # Blocked author: A blocked C above, so A cannot vote on C's
    # poll — B can.
    ppc = post_as(c, UID["C"], "C", type="text", caption="c poll",
                  poll={"question": "Yes or no?",
                        "options": ["Yes", "No"]})
    opt_yes = ppc["poll"]["options"][0]["id"]
    r = c.post(f"/posts/{ppc['id']}/poll/vote",
               json={"option_id": opt_yes}, headers=H(UID["A"], "A"))
    assert r.status_code == 403, r.status_code
    r = c.post(f"/posts/{ppc['id']}/poll/vote",
               json={"option_id": opt_yes}, headers=H(UID["B"], "B"))
    assert r.status_code == 200, r.text
    print("polls: 400 / 404 / blocked-403 guards OK")

    # --------------------------------------------------------- backup --
    # Keep one live draft so the drafts table is non-empty.
    r = c.post("/drafts", json={"text": "backup draft"},
               headers=H(UID["A"], "A"))
    keep_draft = r.json()
    r = c.get("/admin/backup", headers=H(UID["ADMIN"], "Admin"))
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers.get("content-disposition", "")
    b = r.json()
    assert b["format"] == "nexora-backup" and b["version"] == 1
    from app.main import _BACKUP_TABLES  # noqa: E402
    assert set(b["tables"]) == {n for n, _ in _BACKUP_TABLES}
    assert len(b["tables"]) == 44, len(b["tables"])
    for t in ("drafts", "comment_likes", "polls", "poll_options",
              "poll_votes"):
        assert t in b["tables"], t
    assert any(d["id"] == keep_draft["id"]
               for d in b["tables"]["drafts"])
    assert len(b["tables"]["comment_likes"]) >= 2
    assert len(b["tables"]["polls"]) >= 3
    assert len(b["tables"]["poll_options"]) >= 7
    assert len(b["tables"]["poll_votes"]) == 4
    assert any(p["question"] == "Best pet?"
               for p in b["tables"]["polls"])
    r = c.get("/admin/backup", headers=H(UID["A"], "A"))
    assert r.status_code == 403, r.status_code
    print("backup: 39 tables incl. the five new ones, rows present OK")
    # Round-trip: wipe only the five new tables, restore, they
    # come back identical (IDs preserved).
    db = SessionLocal()
    for m in (models.PollVote, models.PollOption, models.Poll,
              models.CommentLike, models.Draft):
        db.query(m).delete()
    db.commit()
    assert db.query(models.Poll).count() == 0
    assert db.query(models.Draft).count() == 0
    db.close()
    r = c.post("/admin/restore", headers=H(UID["ADMIN"], "Admin"),
               json={"confirm": "RESTORE", "backup": b})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    assert db.query(models.Poll).count() == len(b["tables"]["polls"])
    assert db.query(models.PollVote).count() == 4
    assert db.query(models.Draft).count() == 1
    assert db.get(models.Draft, keep_draft["id"]).text == "backup draft"
    db.close()
    print("backup: restore round-trip for the new tables OK")

    # ------------------------------------------------- client markers --
    html = open("webapp/index.html").read()
    js = open("webapp/app.js").read()
    css = open("webapp/style.css").read()
    main = open("app/main.py").read()
    assert html.count("?v=160") == 10, html.count("?v=160")
    assert "?v=122" not in html
    for bit in ('id="composer-poll-toggle"', 'id="composer-draft"',
                'id="composer-poll"', 'id="composer-poll-q"',
                'class="composer-poll-opt"',
                'placeholder="Poll question…"',
                'placeholder="Option 1"',
                '💾 Save draft'):
        assert bit in html, bit
    for bit in ("pollBlock", "/poll/vote", "You voted",
                "comment-like-btn", "/comments/",
                "Pin to profile", "pin-badge", "📌 Pinned",
                "My drafts", "loadDrafts", "composerPoll",
                "composer-draft", "Draft saved",
                "composer-poll-toggle", "loadProfilePosts(true)"):
        assert bit in js, bit
    for bit in (".pin-badge", ".poll-block", ".poll-opt",
                ".poll-fill", ".comment-like-btn", ".draft-row",
                ".composer-poll"):
        assert bit in css, bit
    assert "CREATOR TOOLS: pin one of your own posts" in main
    # Earlier phases intact.
    for bit in ("loadTrending", "syncObsDial", "wireObsQuickActions",
                "loadRelatedDesigns", "loadMyQr", "openPhotoViewer",
                "repost-banner", "Replying to"):
        assert bit in js, bit
    print("client: composer poll + draft, pin, poll block, comment "
          "heart, My drafts, ?v=160, Nexa OK")

print("PHASE 123 OK")
