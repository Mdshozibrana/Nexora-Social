"""Phase-169 tests: Nexora Inbox REMOVED entirely (owner order,
Nov 24, 2026, 20:28 Dhaka — confirmed by tap on
"পুরো Nexora Inbox পেজটাই সরিয়ে দাও").

Phase 167 built the Inbox as a bot-text route (wrong design);
Phase 168 corrected it to an in-page compose box; the owner then
said "Nexora Inbox বাদ দাও" (drop it) and confirmed the scope:
the WHOLE page goes. The Phase 169 redesign discussed earlier
(post-as-Inbox-ID + sender tag) was NOT built — that idea is dead.

Removal guards: no "Nexora Inbox" string anywhere in the client;
no view-inbox / sidebar entry / compose box / loadInbox /
submitInboxPost / startapp=inbox / inbox mascot tips; no GET
/inbox-posts; no via_inbox on PostIn or in post serialization;
no register_post() via_inbox handling; bot.py and config.py
still have zero inbox refs (Phase 168 removal confirmed).

DATA SAFETY (kept): no user post is deleted. Posts already
stored with via_inbox=true stay in the feed as ordinary posts,
and the via_inbox DB column is RETAINED but unused — no
migration drops it. Version + routes (166) + backup 44 tables.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase169.db"
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
MODELS_SRC = open(os.path.join(ROOT, "code/app/models.py")).read()
SERVICES_SRC = open(os.path.join(ROOT, "code/app/services.py")).read()
CONFIG_SRC = open(os.path.join(ROOT, "code/app/config.py")).read()

with TestClient(app) as c:
    # 1. JS parses (node).
    for f in ("code/webapp/app.js", "code/webapp/games.js"):
        r = subprocess.run(["node", "--check", os.path.join(ROOT, f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    print("node --check OK (games.js + app.js parse)")

    # 2. REMOVAL GUARDS — client: no trace of Nexora Inbox.
    assert "Nexora Inbox" not in HTML, "page name must be gone"
    assert "Nexora Inbox" not in JS, "client must not mention Nexora Inbox"
    assert "inbox" not in HTML.lower(), "no inbox string in shell"
    assert "inbox" not in JS.lower(), "no inbox string in client"
    for bit in ('id="view-inbox"', 'data-go="inbox"',
                'id="inbox-text"', 'id="inbox-post"', 'id="inbox-status"',
                'id="inbox-list"', 'id="inbox-more"', 'id="inbox-empty"'):
        assert bit not in HTML, bit
    for marker in ("loadInbox", "submitInboxPost", "inboxCursor",
                   "inbox-text", "inbox-status", "/inbox-posts",
                   'if (p === "inbox")', 'if (name === "inbox")',
                   '"skills", "inbox"]', "  inbox: [",
                   "Write in the box at the top"):
        assert marker not in JS, marker
    assert '"settings", "blood", "skills"].forEach(v => {' in JS, \
        "showView list must end at skills now"
    print("client removal OK (no Inbox strings, view, box, tips)")

    # 3. REMOVAL GUARDS — server: endpoint, PostIn field, serialization.
    assert "/inbox-posts" not in MAIN_SRC, "endpoint must be gone"
    assert "via_inbox: bool = Field" not in MAIN_SRC
    assert '"via_inbox": bool(getattr' not in MAIN_SRC
    assert "via_inbox=body.via_inbox" not in MAIN_SRC
    assert "via_inbox" not in SERVICES_SRC, "register_post handling gone"
    assert "inbox" not in SERVICES_SRC.lower()
    assert "text_handler" not in BOT, "Phase 168 bot removal stands"
    assert "inbox" not in BOT.lower()
    assert "inbox_post" not in CONFIG_SRC
    assert "inbox" not in CONFIG_SRC.lower()
    # Column RETAINED but unused (data safety — never drop it).
    assert "via_inbox BOOLEAN DEFAULT FALSE" in MAIN_SRC
    assert "BOOLEAN DEFAULT 0" not in MAIN_SRC
    assert "via_inbox = Column(Boolean, default=False)" in MODELS_SRC
    print("server removal OK (endpoint + field gone, column retained)")

    # 4. Functional: /inbox-posts is 404; via_inbox ignored on POST /posts.
    r = c.get("/inbox-posts", headers=H(115, "Dana"))
    assert r.status_code == 404, r.status_code
    ratelimit.reset()
    r = c.post("/posts", headers=H(115, "Dana"),
               json={"type": "text", "caption": "Hello #plain",
                     "via_inbox": True})
    assert r.status_code == 200, r.text
    p = r.json()
    assert "via_inbox" not in p, p
    assert p["hashtags"] == "plain", p
    db = SessionLocal()
    try:
        led = db.query(models.PointsLedger).filter_by(
            user_id=115, reason="post", ref_id=p["id"]).all()
        assert len(led) == 1 and led[0].amount == 10, led
    finally:
        db.close()
    print("functional OK (/inbox-posts 404, via_inbox ignored, +10)")

    # 5. DATA SAFETY: an old via_inbox=true post still renders in the feed.
    db = SessionLocal()
    try:
        row = db.get(models.Post, p["id"])
        row.via_inbox = True
        db.commit()
    finally:
        db.close()
    feed = c.get("/feed", headers=H(115, "Dana")).json()["posts"]
    assert p["id"] in [x["id"] for x in feed], \
        "old via_inbox post must stay in the feed"
    assert all("via_inbox" not in x for x in feed), \
        "feed must not leak the retained flag"
    print("data safety OK (old inbox post still in feed, flag not leaked)")

    # 6. Neighbours: composer, sidebar, mascot, other startapp params.
    js = c.get("/webapp/app.js").text
    for marker in ("vname-text", "fitVerifiedNames", "totpGateAdmin",
                   "refreshMediaToken", "bloodDistance", "photo_file_id",
                   "MASCOT_TIPS_BY_VIEW", "loadSkills", "totp-card",
                   "loadBlood", "loadTrending", "postCard"):
        assert marker in js, marker
    assert "Show setup code" not in js, "Phase 166 removal guard"
    assert "  skills: [" in JS and "  blood: [" in JS, \
        "mascot tips for other views must stay"
    assert 'p.indexOf("profile_")' in JS, "profile startapp must stay"
    for bit in ('data-go="skills"', 'data-go="blood"',
                'data-go="messages"', 'id="view-skills"',
                'id="view-blood"'):
        assert bit in HTML, bit
    r = c.post("/posts", headers=H(111, "Alice"),
               json={"type": "text", "caption": "Composer still works #ok"})
    assert r.status_code == 200, r.text
    assert r.json()["hashtags"] == "ok"
    print("neighbours OK (composer, sidebar, mascot, startapp)")

    # 7. Version + routes + backup.
    assert HTML.count("?v=191") == 10, HTML.count("?v=191")
    assert "?v=16" + "8" not in HTML
    assert "app.js?v=191" in HTML and "style.css?v=191" in HTML
    assert 'menu_url.rstrip("/") + "/?v=191"' in BOT
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 184, len(paths)
    assert "/inbox-posts" not in paths and "/posts" in paths, paths
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 191, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
    print("version + routes + backup OK (174 routes, 48 tables, ?v=191)")

print("PHASE 169 OK")
