"""Phase-124 tests: points-history cleanup + clickable task cards.

Server: /me/points keyset paging — default still the latest 20 rows
(newest first); ?before=<oldest id seen> returns the next 20 older
rows; before=0 behaves like the default; pages are disjoint and
together cover the whole ledger.
Client (read from disk, as in test_phase123): points history renders
grouped by day with Today/Yesterday headers, filter chips per reason,
compact one-line rows, and a Show more button that fetches
/me/points?before=<id>; task cards for incomplete tasks carry the
task-go class + chevron and a card-level tap handler that ignores
button taps and claimed cards; follow3 scrolls to the Suggested card
(#suggest-card), comment5 opens the first post's comments
(.cmt-btn), react6 goes to the feed, check-in reuses the claim flow,
and ad-watch reuses showTaskAd behind a !btn.disabled guard.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase124.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

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


with TestClient(app) as c:
    r = c.post("/auth", json={"initData": H(555, "Eve")["X-Init-Data"]})
    assert r.status_code == 200, r.text
    EVE = H(555, "Eve")

    # 25 posts -> 25 ledger rows of +10 (Phase 113 rule).
    for i in range(25):
        r = c.post("/posts", headers=EVE,
                   json={"type": "text", "caption": f"post {i}"})
        assert r.status_code == 200, r.text

    # Default: latest 20, newest first, balance 250.
    pts = c.get("/me/points", headers=EVE).json()
    assert pts["balance"] == 250, pts
    assert len(pts["entries"]) == 20, pts
    ids = [e["id"] for e in pts["entries"]]
    assert ids == sorted(ids, reverse=True), ids
    assert all(e["amount"] == 10 for e in pts["entries"]), pts
    assert all(e["created_at"] for e in pts["entries"]), pts
    print("points: default latest 20, newest first, balance 250 OK")

    # before=<oldest id of page 1> -> the remaining 5 older rows.
    page2 = c.get(f"/me/points?before={ids[-1]}", headers=EVE).json()
    assert len(page2["entries"]) == 5, page2
    ids2 = [e["id"] for e in page2["entries"]]
    assert ids2 == sorted(ids2, reverse=True), ids2
    assert not set(ids) & set(ids2), (ids, ids2)
    assert all(i < ids[-1] for i in ids2), ids2
    assert page2["balance"] == 250, page2
    print("points: ?before= returns the 5 older rows, disjoint OK")

    # before=0 behaves like the default; before=1 exhausts the ledger.
    assert len(c.get("/me/points?before=0", headers=EVE).json()
               ["entries"]) == 20
    assert c.get("/me/points?before=1", headers=EVE).json()["entries"] == []
    # Unauthenticated stays 401.
    assert c.get("/me/points").status_code == 401
    print("points: before=0 default, before=1 empty, 401 OK")

    # Client markers (files on disk).
    html = open("webapp/index.html").read()
    js = open("webapp/app.js").read()
    css = open("webapp/style.css").read()
    assert html.count("?v=172") == 10, html.count("?v=172")
    assert "?v=123" not in html
    # Points history: grouping / chips / compact rows / paging.
    for bit in ("phState", "renderPh", "phDayLabel", "ph-chip",
                "ph-chips", "ph-day", "ph-more", "ph-when",
                '"Today"', '"Yesterday"', "Show more",
                "/me/points?before="):
        assert bit in js, bit
    for bit in (".ph-day", ".ph-chips", ".ph-chip", ".ph-chip.active",
                ".ph-more", ".ph-when", ".ph-empty"):
        assert bit in css, bit
    # The old flat render is gone; the MY POINTS header is untouched.
    assert "pts.entries.forEach(e => {" not in js
    assert "points-head" in js and "MY POINTS" not in js
    assert "My Points" in js and "points-today" in js
    print("client: points history grouped/filtered/paged OK")
    # Tasks: tappable incomplete cards, claimed go nowhere.
    for bit in ("task-go", "task-go-chev", "goFeedTo",
                "goFeedToFirstComment", "#suggest-card",
                "#feed-list .post .cmt-btn", "cmt-btn",
                'ev.target.closest("button")',
                'if (t.claimed) return;',
                'if (t.key === "checkin" && doClaim)',
                'if (t.key === "follow3")',
                'if (t.key === "comment5")',
                'if (t.key === "react6")',
                'if (t.key === "adwatch" && !btn.disabled) showTaskAd(btn)'):
        assert bit in js, bit
    for bit in (".task-card.task-go", ".task-go-chev"):
        assert bit in css, bit
    print("client: task cards clickable, claimed inert, ad single-fire OK")
    # Earlier phases intact (spot check).
    for bit in ("loadTrending", "loadMyQr", "loadRelatedDesigns",
                "repost-banner", "Replying to", "loadDrafts",
                "pollBlock", "comment-like-btn", "syncObsDial"):
        assert bit in js, bit
    print("client: Phase 118-123 markers intact OK")

print("PHASE 124 OK")
