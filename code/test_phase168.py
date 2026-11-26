"""Phase-168 tests CONVERTED to removal guards (Phase 169).

Phase 168 built the Nexora Inbox page's own writing box (owner
correction, Nov 23, 08:52-08:53 Dhaka — the Phase 167 bot-chat
text->post route was removed and the page's box built instead).
On Nov 24, 20:28 Dhaka the owner confirmed the scope —
"পুরো Nexora Inbox পেজটাই সরিয়ে দাও" (remove the WHOLE page)
— and Phase 169 removed the entire feature. This file now
guards that removal: no compose box, no loadInbox /
submitInboxPost, no GET /inbox-posts, no via_inbox posting
path. What Phase 168 proved about the NORMAL composer stays
guarded as neighbours: banned-word 400, 2000-char 422, the
"post" bucket 30/hour. The via_inbox DB column is RETAINED
but unused (data safety — old posts keep their flag).
"""
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase168.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import ratelimit  # noqa: E402
from app.services import BANNED_WORD_MESSAGE  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData",
                      settings.BOT_TOKEN.encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, auth_date=None):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name},
                                          auth_date=auth_date)}


ADMIN = H(999, "Admin")
ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
MAIN_SRC = open(os.path.join(ROOT, "code/app/main.py")).read()


def posts_by(uid, caption=None):
    db = SessionLocal()
    try:
        q = db.query(models.Post).filter_by(user_id=uid)
        if caption is not None:
            q = q.filter_by(caption=caption)
        return q.all()
    finally:
        db.close()


with TestClient(app) as c:
    # 1. JS parses (node).
    for f in ("code/webapp/app.js", "code/webapp/games.js"):
        r = subprocess.run(["node", "--check", os.path.join(ROOT, f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    print("node --check OK (games.js + app.js parse)")

    # 2. REMOVAL GUARDS — the compose box and its code are gone.
    assert "Nexora Inbox" not in HTML and "Nexora Inbox" not in JS
    assert "inbox" not in HTML.lower() and "inbox" not in JS.lower()
    for bit in ('<textarea id="inbox-text"', 'id="inbox-post"',
                'id="inbox-status"', 'id="view-inbox"',
                'data-go="inbox"'):
        assert bit not in HTML, bit
    for marker in ("submitInboxPost", "loadInbox", "inboxCursor",
                   "/inbox-posts", 'if (p === "inbox")',
                   "Write in the box at the top",
                   "Write something for Nexora Inbox"):
        assert marker not in JS and marker not in HTML, marker
    assert HTML.count("?v=190") == 10, HTML.count("?v=190")
    assert "?v=16" + "8" not in HTML
    assert "app.js?v=190" in HTML and "style.css?v=190" in HTML
    assert "/inbox-posts" not in MAIN_SRC
    assert "via_inbox: bool = Field" not in MAIN_SRC
    assert '"via_inbox": bool(getattr' not in MAIN_SRC
    assert "via_inbox BOOLEAN DEFAULT FALSE" in MAIN_SRC, \
        "column DDL must be retained (data safety)"
    assert "BOOLEAN DEFAULT 0" not in MAIN_SRC
    print("box removal OK (?v=190, no box/code/endpoint, column retained)")

    # 3. Functional: /inbox-posts 404; via_inbox ignored on POST /posts.
    r = c.get("/inbox-posts", headers=H(115, "Dana"))
    assert r.status_code == 404, r.status_code
    ratelimit.reset()
    r = c.post("/posts", headers=H(115, "Dana"),
               json={"type": "text", "caption": "Hello from Dana #nexora",
                     "via_inbox": True})
    assert r.status_code == 200, r.text
    p = r.json()
    assert "via_inbox" not in p, p
    assert p["hashtags"] == "nexora", p
    db = SessionLocal()
    try:
        led = db.query(models.PointsLedger).filter_by(
            user_id=115, reason="post", ref_id=p["id"]).all()
        assert len(led) == 1 and led[0].amount == 10, led
    finally:
        db.close()
    feed_ids = [x["id"] for x in c.get("/feed", headers=H(115, "Dana")).json()["posts"]]
    assert p["id"] in feed_ids, "post must appear in the main feed"
    print("via_inbox ignored OK (200, no flag, +10, in feed)")

    # 4. DATA SAFETY: an old via_inbox=true post still renders in the feed.
    db = SessionLocal()
    try:
        row = db.get(models.Post, p["id"])
        row.via_inbox = True
        db.commit()
    finally:
        db.close()
    feed = c.get("/feed", headers=H(115, "Dana")).json()["posts"]
    assert p["id"] in [x["id"] for x in feed]
    assert all("via_inbox" not in x for x in feed)
    print("data safety OK (old inbox post still in feed)")

    # 5. Neighbours: banned-word 400, over-long 422, post bucket 30/hour.
    db = SessionLocal()
    try:
        db.add(models.BannedWord(word="zqxwv", added_by=999))
        db.commit()
    finally:
        db.close()
    try:
        n0 = len(posts_by(115))
        r = c.post("/posts", headers=H(115, "Dana"),
                   json={"type": "text", "caption": "this has ZQXWV inside"})
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == BANNED_WORD_MESSAGE, r.json()
        assert "zqxwv" not in r.json()["detail"].lower()
        assert len(posts_by(115)) == n0
    finally:
        db = SessionLocal()
        try:
            db.query(models.BannedWord).filter_by(word="zqxwv").delete()
            db.commit()
        finally:
            db.close()
    print("banned-word OK (400, word never echoed, no post)")
    r = c.post("/posts", headers=H(115, "Dana"),
               json={"type": "text", "caption": "x" * 2001})
    assert r.status_code == 422, r.text
    print("over-long OK (422)")
    ratelimit.reset()
    for i in range(30):
        r = c.post("/posts", headers=H(4242, "Rater"),
                   json={"type": "text", "caption": f"rate post {i}"})
        assert r.status_code == 200, (i, r.text)
    assert len(posts_by(4242)) == 30
    r = c.post("/posts", headers=H(4242, "Rater"),
               json={"type": "text", "caption": "rate post 30"})
    assert r.status_code == 429, r.text
    assert len(posts_by(4242)) == 30
    print("rate limit OK (post bucket, 30/hour, 31st 429)")

    # 6. Neighbours + version + routes.
    js = c.get("/webapp/app.js").text
    for marker in ("vname-text", "fitVerifiedNames", "totpGateAdmin",
                   "refreshMediaToken", "bloodDistance", "photo_file_id",
                   "MASCOT_TIPS_BY_VIEW", "loadSkills", "totp-card",
                   "loadBlood", "loadTrending", "postCard"):
        assert marker in js, marker
    assert "Show setup code" not in js, "Phase 166 removal guard"
    assert "text_handler" not in open(os.path.join(ROOT, "code/app/bot.py")).read()
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 184, len(paths)
    assert "/inbox-posts" not in paths and "/posts" in paths, paths
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 190, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
    print("neighbours + version + routes OK (174 routes, 48 tables, ?v=190)")

print("PHASE 168 REMOVAL GUARDS OK")
