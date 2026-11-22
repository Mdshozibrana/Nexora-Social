"""Phase-167 tests: Nexora Inbox (owner, Nov 22, 23:54 Dhaka — page
named "Nexora Inbox" Nov 22, 23:58 Dhaka).

A plain-text message sent to @NexoraSocial_bot in chat becomes a post
authored by the sender — on the new Nexora Inbox page AND in the main
feed. It goes through the SAME shared post path as the composer
(register_post): +10 points, banned-word check, hashtag extraction,
first-post referral qualification. via_inbox flags the origin.

Covers: bot text->post + flag + points + hashtags; post in /feed and
/inbox-posts; composer posts NOT in /inbox-posts; empty/over-long
text refused; banned-word text refused (plain reply, word never
echoed); rate limit 30/hour; commands excluded by the handler filter
(source-level: filters.TEXT & ~filters.COMMAND); private-account +
block visibility on /inbox-posts; client markers (page, sidebar,
loadInbox, startapp=inbox, mascot tips); version + routes (167) +
backup 44 tables; source guard (no BOOLEAN DEFAULT 0).
"""
import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase167.db"
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
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
MAIN_SRC = open(os.path.join(ROOT, "code/app/main.py")).read()


class FakeMsg:
    def __init__(self, text):
        self.text = text
        self.caption = ""
        self.sent = []
        self.markup = None

    async def reply_text(self, text, reply_markup=None):
        self.sent.append(text)
        self.markup = reply_markup
        return None


class FakeUser:
    def __init__(self, uid, name):
        self.id = uid
        self.username = name.lower()
        self.first_name = name


class FakeUpdate:
    def __init__(self, uid, name, text):
        self.effective_user = FakeUser(uid, name)
        self.message = FakeMsg(text)


class FakeCtx:
    pass


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

    # 2. Client markers: Nexora Inbox page + sidebar + loader.
    assert HTML.count("?v=167") == 10, HTML.count("?v=167")
    assert "?v=16" + "6" not in HTML
    assert "app.js?v=167" in HTML and "style.css?v=167" in HTML
    assert "Nexora Inbox" in HTML, "page name must read Nexora Inbox"
    assert 'data-go="inbox"' in HTML
    assert ">Nexora Inbox</span>" in HTML, "sidebar label is Nexora Inbox"
    assert '<h2 class="view-title">📥 Nexora Inbox</h2>' in HTML
    for bit in ('id="view-inbox"', 'id="inbox-list"',
                'id="inbox-more"', 'id="inbox-empty"'):
        assert bit in HTML, bit
    for marker in ("loadInbox", "/inbox-posts", "inboxCursor",
                   'if (p === "inbox")', '"skills", "inbox"]',
                   'if (name === "inbox") loadInbox();',
                   "  inbox: [",
                   '$("inbox-more").onclick'):
        assert marker in JS, marker
    for marker in ("text_handler", "filters.TEXT & ~filters.COMMAND",
                   "startapp=inbox", "See it on Nexora Inbox",
                   "via_inbox=True", '"inbox_post"',
                   'menu_url.rstrip("/") + "/?v=167"'):
        assert marker in BOT, marker
    assert "BOOLEAN DEFAULT 0" not in MAIN_SRC, \
        "boolean DEFAULT 0 present"
    assert "via_inbox BOOLEAN DEFAULT FALSE" in MAIN_SRC
    print("client + bot markers OK (Nexora Inbox, ?v=167)")

    # 3. Composer post is a normal post: via_inbox False.
    r = c.post("/posts", headers=H(111, "Alice"),
               json={"type": "text", "caption": "Composer post #plain"})
    assert r.status_code == 200, r.text
    comp = r.json()
    assert comp["via_inbox"] is False, comp
    assert comp["hashtags"] == "plain", comp
    print("composer post OK (via_inbox False)")

    # 4. Bot text -> post: flag, points, hashtags, feed + inbox, button.
    upd = FakeUpdate(115, "Dana", "Hello from the bot #nexora")
    asyncio.run(bot_mod.text_handler(upd, FakeCtx()))
    assert len(upd.message.sent) == 1, upd.message.sent
    assert upd.message.sent[0].startswith("✅ Posted to "), upd.message.sent
    assert "First post bonus" in upd.message.sent[0], upd.message.sent
    rows = posts_by(115, "Hello from the bot #nexora")
    assert len(rows) == 1, len(rows)
    p = rows[0]
    assert p.type == "text" and p.via_inbox is True, (p.type, p.via_inbox)
    assert p.hashtags == "nexora", p.hashtags
    assert p.media_file_id is None
    db = SessionLocal()
    try:
        led = db.query(models.PointsLedger).filter_by(
            user_id=115, reason="post", ref_id=p.id).all()
        assert len(led) == 1 and led[0].amount == 10, led
    finally:
        db.close()
    btn = upd.message.markup.inline_keyboard[0][0]
    assert "startapp=inbox" in btn.url, btn.url
    assert btn.url.startswith("https://t.me/NexoraSocial_bot/nexorasocial"), btn.url
    assert "See it on Nexora Inbox" in btn.text, btn.text
    feed_ids = [x["id"] for x in c.get("/feed", headers=H(115, "Dana")).json()["posts"]]
    assert p.id in feed_ids, "inbox post must appear in the main feed"
    inbox_ids = [x["id"] for x in c.get("/inbox-posts", headers=H(115, "Dana")).json()["posts"]]
    assert p.id in inbox_ids, "inbox post must appear on Nexora Inbox"
    assert comp["id"] not in inbox_ids, "composer post must NOT be on Nexora Inbox"
    print("bot text->post OK (flag, +10, hashtags, feed + inbox, button)")

    # 5. Empty / whitespace-only text is ignored, silently.
    n0 = len(posts_by(115))
    upd = FakeUpdate(115, "Dana", "   \n  ")
    asyncio.run(bot_mod.text_handler(upd, FakeCtx()))
    assert upd.message.sent == [], upd.message.sent
    assert len(posts_by(115)) == n0
    print("empty text OK (ignored, no reply, no post)")

    # 6. Over-long text (composer limit is 2000) is refused.
    upd = FakeUpdate(115, "Dana", "x" * 2001)
    asyncio.run(bot_mod.text_handler(upd, FakeCtx()))
    assert any("too long" in t for t in upd.message.sent), upd.message.sent
    assert len(posts_by(115)) == n0
    print("over-long text OK (refused, no post)")

    # 7. Banned-word text is refused, word never echoed.
    db = SessionLocal()
    try:
        db.add(models.BannedWord(word="zqxwv", added_by=999))
        db.commit()
    finally:
        db.close()
    try:
        upd = FakeUpdate(115, "Dana", "this has ZQXWV inside")
        asyncio.run(bot_mod.text_handler(upd, FakeCtx()))
        assert upd.message.sent == [BANNED_WORD_MESSAGE], upd.message.sent
        assert "zqxwv" not in upd.message.sent[0].lower()
        assert len(posts_by(115)) == n0
    finally:
        db = SessionLocal()
        try:
            db.query(models.BannedWord).filter_by(word="zqxwv").delete()
            db.commit()
        finally:
            db.close()
    print("banned-word text OK (refused, word never echoed)")

    # 8. Rate limit: 30/hour per user, the 31st is refused.
    ratelimit.reset()
    for i in range(30):
        upd = FakeUpdate(4242, "Rater", f"rate post {i}")
        asyncio.run(bot_mod.text_handler(upd, FakeCtx()))
        assert upd.message.sent[0].startswith("✅ Posted"), (i, upd.message.sent)
    assert len(posts_by(4242)) == 30
    upd = FakeUpdate(4242, "Rater", "rate post 30")
    asyncio.run(bot_mod.text_handler(upd, FakeCtx()))
    assert any("posting a bit fast" in t for t in upd.message.sent), upd.message.sent
    assert len(posts_by(4242)) == 30
    print("rate limit OK (30/hour, 31st refused)")

    # 9. Commands never reach the handler: the filter excludes them.
    assert "MessageHandler(filters.TEXT & ~filters.COMMAND," in BOT
    assert 'CommandHandler("start", start_handler)' in BOT
    assert "MessageHandler(filters.TEXT & ~filters.COMMAND,\n" \
           "                                   text_handler)" in BOT
    print("command exclusion OK (filters.TEXT & ~filters.COMMAND)")

    # 10. Privacy + blocks on /inbox-posts.
    upd = FakeUpdate(222, "Bob", "Bob's private inbox post")
    asyncio.run(bot_mod.text_handler(upd, FakeCtx()))
    bob_post = posts_by(222, "Bob's private inbox post")[0]
    db = SessionLocal()
    try:
        db.get(models.User, 222).is_private = True
        db.commit()
    finally:
        db.close()
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(111, "Alice")).json()["posts"]]
    assert bob_post.id not in ids, "private author's post must hide from strangers"
    db = SessionLocal()
    try:
        db.add(models.Follow(follower_id=111, following_id=222))
        db.commit()
    finally:
        db.close()
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(111, "Alice")).json()["posts"]]
    assert bob_post.id in ids, "follower must see a private author's inbox post"
    db = SessionLocal()
    try:
        db.add(models.UserBlock(blocker_id=111, blocked_id=222))
        db.commit()
    finally:
        db.close()
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(111, "Alice")).json()["posts"]]
    assert bob_post.id not in ids, "blocked author's post must hide"
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(333, "Carol")).json()["posts"]]
    assert bob_post.id not in ids, "private author's post must hide from Carol too"
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(222, "Bob")).json()["posts"]]
    assert bob_post.id in ids, "author always sees their own inbox post"
    print("privacy + block OK (private hidden, follower sees, blocked hidden)")

    # 11. Neighbours + version + routes.
    js = c.get("/webapp/app.js").text
    for marker in ("vname-text", "fitVerifiedNames", "totpGateAdmin",
                   "refreshMediaToken", "bloodDistance", "photo_file_id",
                   "MASCOT_TIPS_BY_VIEW", "loadSkills", "totp-card",
                   "loadInbox", "loadBlood", "loadTrending", "postCard"):
        assert marker in js, marker
    assert "Show setup code" not in js, "Phase 166 removal guard"
    assert "photo_handler" in BOT and "video_handler" in BOT, \
        "bot media route must stay registered"
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 167, len(paths)
    assert "/inbox-posts" in paths, paths
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 167, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 44, len(r.json()["tables"])
    print("neighbours + version + routes OK (167 routes, 44 tables, ?v=167)")

print("PHASE 167 OK")
