"""Phase-206 tests: notification tap opens the POST, not the profile.

Owner bug (Nov 27, 22:33): when someone reacted to or commented on
a post, tapping that notification opened the commenter's profile
instead of the post. Root cause was loadNotifications: every row
with an actor_id got row.onclick = () => openProfile(n.actor_id),
regardless of type. Phase 206 routes on the data: a row carrying
post_id opens the post via the Phase 134 single-post opener
(openTopPost — the app has no single-post view, the card in the
sheet IS the view); rows with no post_id keep opening the actor's
profile (follow / follow_request / message / blood / skill).
Post-carrying types, verified against every record() call site:
like, comment, reply, repost, mention, post share, post_live.
No new routes, no schema change; GET /me/notifications already
returned post_id per row. Plain script (run.sh runs it directly).
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase206.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _health_version  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402
from app import notify as notify_mod  # noqa: E402
import subprocess  # noqa: E402

def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}




ALICE = H(2061, "Alice", "alice")
BOB = H(2062, "Bob", "bob")
CAROL = H(2063, "Carol", "carol")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
MAIN = open(os.path.join(ROOT, "code/app/main.py")).read()
SERVICES = open(os.path.join(ROOT, "code/app/services.py")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()

c = TestClient(app)


def mk(uid, name, username):
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        u = db.get(models.User, uid)
        assert u is not None, "user %s not created" % uid
        u.username = username
        db.commit()
    finally:
        db.close()


mk(2061, "Alice", "alice")
mk(2062, "Bob", "bob")
mk(2063, "Carol", "carol")

# Re-run safety: only rows created by THIS run count. (run.sh wipes
# test_*.db first, so the regression always starts fresh — but a
# standalone re-run must not trip on the previous run's rows, which
# legitimately point at the previous run's posts.)
with SessionLocal() as db:
    _top = db.query(models.Notification.id).order_by(
        models.Notification.id.desc()).first()
    BEFORE_MAX = _top[0] if _top else 0


def notifs(headers):
    r = c.get("/me/notifications?limit=50", headers=headers)
    assert r.status_code == 200, r.text
    return [n for n in r.json()["notifications"]
            if n["id"] > BEFORE_MAX]


def rows_of(rows, ntype):
    return [n for n in rows if n["type"] == ntype]


def check_post_rows(rows, ntype, pid, actor):
    """Every row of a post-targeting type must carry that post id.
    actor may be one id or a set (comment rows come from Bob's
    comment AND Carol's parent comment)."""
    actors = actor if isinstance(actor, set) else {actor}
    hits = rows_of(rows, ntype)
    assert len(hits) >= 1, (ntype, "no rows")
    for n in hits:
        assert n["post_id"] == pid, (ntype, n)
        assert n["actor_id"] in actors, (ntype, n)


# --- 1. Client: post rows open the post, person rows open the profile.
NEW_BLOCK = """      // Phase 206: a notification whose target is a post opens
      // the post, not the actor's profile. like / comment / reply /
      // repost / mention / post share / post_live all carry post_id;
      // follow / follow_request / message / blood / skill rows have
      // no post_id and keep opening the actor's profile.
      if (n.post_id) {
        row.style.cursor = "pointer";
        row.onclick = () => openTopPost(n.post_id);
      } else if (n.actor_id) {
        row.style.cursor = "pointer";
        row.onclick = () => openProfile(n.actor_id);
      }
"""
assert NEW_BLOCK in JS, "Phase 206 routing block missing from app.js"
OLD_BLOCK = """      if (n.actor_id) {
        row.style.cursor = "pointer";
        row.onclick = () => openProfile(n.actor_id);
      }
"""
assert OLD_BLOCK not in JS, "old unconditional profile tap still in app.js"
# The routing is data-driven (post_id presence), not a type list:
# loadNotifications must not branch on n.type for the tap target.
m = re.search(r"async function loadNotifications\(reset\) \{.*?\n\}\n\$\(\"notif-more\"\)",
              JS, re.S)
assert m, "loadNotifications not found"
assert "n.type ===" not in m.group(0), "tap routes on type, not post_id"
assert "openTopPost" in m.group(0), "loadNotifications never opens a post"
# The Phase 134 single-post opener is what the tap uses.
assert "async function openTopPost(postId)" in JS
assert 'api("/posts/" + postId)' in JS
print("1. client routing: post rows -> openTopPost, person rows -> profile OK")

# --- 2. Server: every post-targeting notification carries post_id. ----
# (like / repost / follow are toggles, so re-like / re-follow on a
# re-run: the checks below are >= 1 row + every row carries the
# right post_id, which holds across re-runs.)
r = c.post("/posts", headers=ALICE,
           json={"type": "text", "caption": "phase 206 post"})
assert r.status_code == 200, r.text
pid = r.json()["id"]

r = c.post(f"/posts/{pid}/like", headers=BOB)
if not r.json()["liked"]:
    r = c.post(f"/posts/{pid}/like", headers=BOB)
assert r.json()["liked"] is True, r.json()
r = c.post(f"/posts/{pid}/comments", headers=BOB,
           json={"text": "phase 206 comment"})
assert r.status_code == 200, r.text
# The reply's parent must be a THIRD member's comment: a reply to
# the post author's own comment notifies her as "comment" only
# (the reply branch skips parent == post author, "already told").
r = c.post(f"/posts/{pid}/comments", headers=CAROL,
           json={"text": "phase 206 parent comment"})
assert r.status_code == 200, r.text
parent_id = r.json()["id"]
r = c.post(f"/posts/{pid}/comments", headers=BOB,
           json={"text": "phase 206 reply", "parent_id": parent_id})
assert r.status_code == 200, r.text
r = c.post(f"/posts/{pid}/repost", headers=BOB)
if not r.json()["reposted"]:
    r = c.post(f"/posts/{pid}/repost", headers=BOB)
assert r.json()["reposted"] is True, r.json()
r = c.post("/posts", headers=ALICE,
           json={"type": "text", "caption": "@bob phase 206 mention"})
assert r.status_code == 200, r.text
mpid = r.json()["id"]
r = c.post(f"/posts/{pid}/share", headers=BOB,
           json={"to_user_id": 2063})
assert r.status_code == 200, r.text
r = c.post("/users/2061/follow", headers=BOB)
if not r.json()["following"]:
    r = c.post("/users/2061/follow", headers=BOB)
assert r.json()["following"] is True, r.json()
# post_live has no API seed path (bot upload); record it directly.
with SessionLocal() as db:
    notify_mod.record(db, 2061, "post_live", post_id=pid,
                      text="Your video is now live on Nexora Social!")

rows = notifs(ALICE)
check_post_rows(rows, "like", pid, 2062)
check_post_rows(rows, "comment", pid, {2062, 2063})
check_post_rows(rows, "repost", pid, 2062)
check_post_rows(rows, "post_live", pid, None)
follows = rows_of(rows, "follow")
assert len(follows) >= 1, "no follow row"
for n in follows:
    assert n["post_id"] is None, n
    assert n["actor_id"] == 2062, n
brows = notifs(BOB)
check_post_rows(brows, "mention", mpid, 2061)
crows = notifs(CAROL)
check_post_rows(crows, "share", pid, 2062)
check_post_rows(crows, "reply", pid, 2062)
print("2. server: like/comment/reply/repost/mention/share/post_live "
      "carry post_id; follow does not OK")

# --- 3. Source guard: the API already returns post_id per row. --------
assert '"post_id": n.post_id' in MAIN, "API does not return post_id"
# Every record() site that passes a post_id is a post-targeting type
# (like/comment/reply/repost/mention/share/post_live) — a future
# post-carrying type is routed by the same post_id rule, and no
# person-targeting record smuggles a post_id in. (Chunk scan: each
# record() call fits in 400 chars; the type is its 3rd argument.)
POST_TYPES = {"like", "comment", "reply", "repost", "mention",
              "share", "post_live"}
for _src in (MAIN, SERVICES):
    for m2 in re.finditer(r"notify\.record\(", _src):
        chunk = _src[m2.start():m2.start() + 400]
        tm = re.search(r'notify\.record\(\s*db,.*?,\s*"(\w+)"', chunk, re.S)
        assert tm, chunk[:120]
        if "post_id=" in chunk:
            assert tm.group(1) in POST_TYPES, (tm.group(1), chunk[:160])
print("3. API returns post_id; record() post_id inventory clean OK")

# --- 4. Version pins + routes + backup + health. -----------------------
assert HTML.count("?v=207") == 10, HTML.count("?v=207")
assert "?v=20" + "6" not in HTML
assert "app.js?v=207" in HTML and "games.js?v=207" in HTML
assert "style.css?v=207" in HTML
assert 'menu_url.rstrip("/") + "/?v=207"' in BOT
assert ("/?v=20" + "6") not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 191, len(paths)
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert _health_version() == 207, _health_version()
print("4. version ?v=207, routes 191, backup 55, health 206 OK")

# --- 5. app.js still parses + the Node harness proves the tap routing. -
r = subprocess.run(["node", "--check",
                    os.path.join(ROOT, "code/webapp/app.js")],
                   capture_output=True, text=True)
assert r.returncode == 0, r.stderr
h = subprocess.run(["node",
                    os.path.join(DESIGNS, "phase206_notif_proof.js"),
                    os.path.join(ROOT, "code/webapp/app.js")],
                   capture_output=True, text=True)
print(h.stdout)
assert h.returncode == 0, h.stdout + h.stderr
print("5. node --check + notif harness OK")

print("PHASE 206 OK (notification tap opens the post, not the profile)")
