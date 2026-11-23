"""Phase-167 tests CONVERTED to removal guards (Phase 168).

Phase 167 built a bot-chat text->post route on a misunderstood
brief. The owner corrected it Nov 23, 08:52 Dhaka ("you didn't
actually understand the feature") and ordered the bot route
REMOVED — only the Nexora Inbox page's own writing box stays
(Phase 168). This file now guards that removal: no text_handler,
no TEXT handler registration, no inbox_post rate bucket, the
/start welcome text back to its pre-167 wording, and plain-text
messages to the bot do nothing. What Phase 167 built correctly
stays and is guarded too: via_inbox flag, GET /inbox-posts, the
Nexora Inbox page + sidebar, feed inclusion.
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
from app.config import RATE_LIMITS, settings  # noqa: E402


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
CONFIG_SRC = open(os.path.join(ROOT, "code/app/config.py")).read()

with TestClient(app) as c:
    # 1. JS parses (node).
    for f in ("code/webapp/app.js", "code/webapp/games.js"):
        r = subprocess.run(["node", "--check", os.path.join(ROOT, f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    print("node --check OK (games.js + app.js parse)")

    # 2. REMOVAL GUARDS — the bot text->post route is gone.
    assert "text_handler" not in BOT, "Phase 168: text_handler must be gone"
    assert "filters.TEXT" not in BOT, "Phase 168: no TEXT handler must remain"
    assert "See it on Nexora Inbox" not in BOT, \
        "Phase 168: bot confirmation button must be gone"
    assert "✅ Posted to " in BOT, \
        "media-route confirmation must survive (only the inbox button goes)"
    assert "or just send me a text" not in BOT, \
        "Phase 168: /start must not promise bot text posting"
    assert "Send a photo with the caption #profile" in BOT, \
        "pre-167 /start welcome text must be restored"
    assert "inbox_post" not in BOT and "inbox_post" not in CONFIG_SRC, \
        "Phase 168: bot-only inbox_post bucket must be gone"
    assert "inbox_post" not in RATE_LIMITS, RATE_LIMITS
    assert "ratelimit" not in BOT and "RATE_LIMITS" not in BOT, \
        "Phase 168: bot.py must not import the removed rate code"
    # Functional: the built bot app registers no text handler at all.
    bot_app = bot_mod.build_bot_app()
    callbacks = [getattr(h.callback, "__name__", "?")
                 for group in bot_app.handlers.values() for h in group]
    assert "text_handler" not in callbacks, callbacks
    assert "photo_handler" in callbacks and "video_handler" in callbacks, \
        "bot media route must stay registered"
    print("bot route removal OK (no text handler, no bucket, welcome restored)")

    # 3. What stays: via_inbox flag, /inbox-posts, page + sidebar.
    assert "via_inbox BOOLEAN DEFAULT FALSE" in MAIN_SRC
    assert "BOOLEAN DEFAULT 0" not in MAIN_SRC, \
        "boolean DEFAULT 0 present"
    assert 'via_inbox = Column(Boolean, default=False)' in \
        open(os.path.join(ROOT, "code/app/models.py")).read()
    assert HTML.count("?v=168") == 10, HTML.count("?v=168")
    assert "?v=16" + "7" not in HTML
    assert "app.js?v=168" in HTML and "style.css?v=168" in HTML
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
    assert "Send the bot a text message" not in JS, \
        "Phase 168: mascot tip must not mention bot text posting"
    print("kept parts OK (via_inbox, /inbox-posts, page, ?v=168)")

    # 4. Neighbours + version + routes.
    js = c.get("/webapp/app.js").text
    for marker in ("vname-text", "fitVerifiedNames", "totpGateAdmin",
                   "refreshMediaToken", "bloodDistance", "photo_file_id",
                   "MASCOT_TIPS_BY_VIEW", "loadSkills", "totp-card",
                   "loadInbox", "loadBlood", "loadTrending", "postCard"):
        assert marker in js, marker
    assert "Show setup code" not in js, "Phase 166 removal guard"
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 167, len(paths)
    assert "/inbox-posts" in paths, paths
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 168, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 44, len(r.json()["tables"])
    print("neighbours + version + routes OK (167 routes, 44 tables, ?v=168)")

print("PHASE 167 REMOVAL GUARDS OK")
