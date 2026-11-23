"""Phase-168 tests: Nexora Inbox's own writing box (owner correction,
Nov 23, 08:52-08:53 Dhaka — Phase 167 built a bot-chat text->post
route on a misunderstood brief; the owner ordered the bot route
REMOVED and the page's box built instead).

The Nexora Inbox page has a textarea + Post button at the top. The
user writes THERE and it posts as them — on the page AND in the
main feed — through the SAME POST /posts path as the composer
(with via_inbox=true): +10 points, banned-word check, hashtag
extraction, 2000-char limit, composer's own "post" rate bucket
(30/hour, no new bucket). Empty/over-long text is refused in the
box with a plain message, never posted silently.

Covers: compose-box markers + a Node harness driving the real
submitInboxPost() (empty / over-long / valid / api-error);
POST /posts via_inbox=true (flag, +10, hashtags, feed + inbox);
composer post excluded from Inbox; banned-word 400; over-long 422;
"post" bucket 30/hour; private-account + block visibility on
/inbox-posts; version + routes (167) + backup 44 tables; source
guard (no BOOLEAN DEFAULT 0).
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
APP_JS_PATH = os.path.join(ROOT, "code/webapp/app.js")


def _extract_submit_src():
    js = open(APP_JS_PATH).read()
    start = js.index("async function submitInboxPost() {")
    end = js.index("// ------------------------------------------------------------- trending")
    assert 0 <= start < end, (start, end)
    src = js[start:end]
    assert "via_inbox: true" in src, "box must post with via_inbox"
    assert '$("inbox-text")' in src and '$("inbox-status")' in src
    return src


HARNESS_PRELUDE = r'''
"use strict";
const els = {};
function makeEl(id) {
  const el = { id, value: "", textContent: "", disabled: false };
  els[id] = el;
  return el;
}
["inbox-text", "inbox-status", "inbox-post"].forEach(makeEl);
function $(id) { return els[id]; }
let apiCalls = [];
let apiFail = null;
async function api(path, opts) {
  apiCalls.push({ path, opts });
  if (apiFail) throw new Error(apiFail);
  return { id: 101 };
}
let loadInboxCalls = [];
function loadInbox(reset) { loadInboxCalls.push(reset); }
let statuses = [];
function setStatus(m) { statuses.push(m); }
function assert(c, msg) { if (!c) throw new Error("ASSERT FAILED: " + msg); }
'''

HARNESS_MAIN = r'''
(async () => {
  const ta = $("inbox-text"), st = $("inbox-status"), btn = $("inbox-post");
  // A: empty / whitespace-only — no api call, plain message.
  ta.value = "   \n  "; apiCalls = []; loadInboxCalls = [];
  await submitInboxPost();
  assert(apiCalls.length === 0, "empty must not call api");
  assert(st.textContent.indexOf("Write something first") === 0,
         "empty status, got " + st.textContent);
  assert(btn.disabled === false, "button enabled after empty");
  // B: over-long (>2000) — no api call, plain message.
  ta.value = "x".repeat(2001); apiCalls = [];
  await submitInboxPost();
  assert(apiCalls.length === 0, "over-long must not call api");
  assert(st.textContent.indexOf("Too long") === 0,
         "over-long status, got " + st.textContent);
  // C: valid — one POST with via_inbox, cleared, list reloaded.
  ta.value = "Hello inbox #test"; apiCalls = []; loadInboxCalls = []; statuses = [];
  await submitInboxPost();
  assert(apiCalls.length === 1, "valid must call api once");
  assert(apiCalls[0].path === "/posts", "path must be /posts");
  const body = JSON.parse(apiCalls[0].opts.body);
  assert(body.type === "text" && body.caption === "Hello inbox #test" &&
         body.via_inbox === true, "body: " + apiCalls[0].opts.body);
  assert(ta.value === "", "textarea cleared after post");
  assert(st.textContent.indexOf("Posted") === 0,
         "posted status, got " + st.textContent);
  assert(loadInboxCalls.length === 1 && loadInboxCalls[0] === true,
         "loadInbox(true) after post");
  assert(btn.disabled === false, "button re-enabled after post");
  // D: api throws — error shown, button re-enabled, no crash.
  ta.value = "boom test"; apiCalls = []; apiFail = "Server down";
  await submitInboxPost();
  assert(apiCalls.length === 1, "failed post still calls api");
  assert(st.textContent === "Server down",
         "error status, got " + st.textContent);
  assert(btn.disabled === false, "button re-enabled after error");
  console.log("HARNESS OK (empty, over-long, valid, error)");
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_node_harness():
    src = _extract_submit_src()
    harness = HARNESS_PRELUDE + src + HARNESS_MAIN
    path = "/tmp/t168_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("node harness OK (submitInboxPost: empty, over-long, valid, error)")


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

    # 2. Node harness: the real submitInboxPost() against DOM stubs.
    _run_node_harness()

    # 3. Compose-box markers in the served shell + client source.
    assert HTML.count("?v=168") == 10, HTML.count("?v=168")
    assert "?v=16" + "7" not in HTML
    assert "app.js?v=168" in HTML and "style.css?v=168" in HTML
    assert '<textarea id="inbox-text" rows="3" maxlength="2000"' in HTML
    assert 'placeholder="Write something for Nexora Inbox' in HTML
    assert '<button id="inbox-post" class="btn">Post</button>' in HTML
    assert 'id="inbox-status"' in HTML
    assert "Write in the box below" in HTML, "hint must describe the box"
    assert "send the bot a text message" not in HTML.lower(), \
        "page must not mention bot text posting any more"
    for marker in ("submitInboxPost", "via_inbox: true",
                   '$("inbox-post").onclick = submitInboxPost;',
                   "Write in the box at the top"):
        assert marker in JS, marker
    assert "Send the bot a text message" not in JS
    assert "See it on Nexora Inbox" not in JS
    assert "BOOLEAN DEFAULT 0" not in MAIN_SRC
    print("compose-box markers OK (?v=168, box + button + status)")

    # 4. POST /posts with via_inbox=true: flag, +10, hashtags, feed + inbox.
    ratelimit.reset()
    r = c.post("/posts", headers=H(115, "Dana"),
               json={"type": "text", "caption": "Hello from the box #nexora",
                     "via_inbox": True})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["via_inbox"] is True, p
    assert p["hashtags"] == "nexora", p
    assert p["type"] == "text" and p["media_file_id"] is None
    db = SessionLocal()
    try:
        led = db.query(models.PointsLedger).filter_by(
            user_id=115, reason="post", ref_id=p["id"]).all()
        assert len(led) == 1 and led[0].amount == 10, led
    finally:
        db.close()
    feed_ids = [x["id"] for x in c.get("/feed", headers=H(115, "Dana")).json()["posts"]]
    assert p["id"] in feed_ids, "inbox post must appear in the main feed"
    inbox_ids = [x["id"] for x in c.get("/inbox-posts", headers=H(115, "Dana")).json()["posts"]]
    assert p["id"] in inbox_ids, "inbox post must appear on Nexora Inbox"
    print("inbox post OK (flag, +10, hashtags, feed + inbox)")

    # 5. Composer post (no via_inbox) is a normal post, NOT on Inbox.
    r = c.post("/posts", headers=H(111, "Alice"),
               json={"type": "text", "caption": "Composer post #plain"})
    assert r.status_code == 200, r.text
    comp = r.json()
    assert comp["via_inbox"] is False, comp
    inbox_ids = [x["id"] for x in c.get("/inbox-posts", headers=H(111, "Alice")).json()["posts"]]
    assert comp["id"] not in inbox_ids, "composer post must NOT be on Nexora Inbox"
    print("composer post OK (via_inbox False, excluded from Inbox)")

    # 6. Banned-word text via the box is refused, word never echoed.
    db = SessionLocal()
    try:
        db.add(models.BannedWord(word="zqxwv", added_by=999))
        db.commit()
    finally:
        db.close()
    try:
        n0 = len(posts_by(115))
        r = c.post("/posts", headers=H(115, "Dana"),
                   json={"type": "text", "caption": "this has ZQXWV inside",
                         "via_inbox": True})
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

    # 7. Over-long caption is refused by the server (422, max 2000).
    r = c.post("/posts", headers=H(115, "Dana"),
               json={"type": "text", "caption": "x" * 2001,
                     "via_inbox": True})
    assert r.status_code == 422, r.text
    print("over-long OK (422)")

    # 8. Rate limit: the composer's own "post" bucket, 30/hour.
    ratelimit.reset()
    for i in range(30):
        r = c.post("/posts", headers=H(4242, "Rater"),
                   json={"type": "text", "caption": f"rate post {i}",
                         "via_inbox": True})
        assert r.status_code == 200, (i, r.text)
    assert len(posts_by(4242)) == 30
    r = c.post("/posts", headers=H(4242, "Rater"),
               json={"type": "text", "caption": "rate post 30",
                     "via_inbox": True})
    assert r.status_code == 429, r.text
    assert len(posts_by(4242)) == 30
    print("rate limit OK (composers post bucket, 30/hour, 31st 429)")

    # 9. Privacy + blocks on /inbox-posts.
    ratelimit.reset()
    r = c.post("/posts", headers=H(222, "Bob"),
               json={"type": "text", "caption": "Bob's private inbox post",
                     "via_inbox": True})
    assert r.status_code == 200, r.text
    bob_post = r.json()
    db = SessionLocal()
    try:
        db.get(models.User, 222).is_private = True
        db.commit()
    finally:
        db.close()
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(111, "Alice")).json()["posts"]]
    assert bob_post["id"] not in ids, "private author's post must hide from strangers"
    db = SessionLocal()
    try:
        db.add(models.Follow(follower_id=111, following_id=222))
        db.commit()
    finally:
        db.close()
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(111, "Alice")).json()["posts"]]
    assert bob_post["id"] in ids, "follower must see a private author's inbox post"
    db = SessionLocal()
    try:
        db.add(models.UserBlock(blocker_id=111, blocked_id=222))
        db.commit()
    finally:
        db.close()
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(111, "Alice")).json()["posts"]]
    assert bob_post["id"] not in ids, "blocked author's post must hide"
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(333, "Carol")).json()["posts"]]
    assert bob_post["id"] not in ids, "private author's post must hide from Carol too"
    ids = [x["id"] for x in c.get("/inbox-posts", headers=H(222, "Bob")).json()["posts"]]
    assert bob_post["id"] in ids, "author always sees their own inbox post"
    print("privacy + block OK (private hidden, follower sees, blocked hidden)")

    # 10. Neighbours + version + routes.
    js = c.get("/webapp/app.js").text
    for marker in ("vname-text", "fitVerifiedNames", "totpGateAdmin",
                   "refreshMediaToken", "bloodDistance", "photo_file_id",
                   "MASCOT_TIPS_BY_VIEW", "loadSkills", "totp-card",
                   "loadInbox", "submitInboxPost", "loadBlood",
                   "loadTrending", "postCard"):
        assert marker in js, marker
    assert "Show setup code" not in js, "Phase 166 removal guard"
    assert "text_handler" not in open(os.path.join(ROOT, "code/app/bot.py")).read()
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 167, len(paths)
    assert "/inbox-posts" in paths and "/posts" in paths, paths
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 168, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 44, len(r.json()["tables"])
    print("neighbours + version + routes OK (167 routes, 44 tables, ?v=168)")

print("PHASE 168 OK")
