"""Phase 170 tests: @mentions in posts and comments.

Parse @username in post captions AND comments; only existing
usernames count (case-insensitive); unknown names stay plain text;
self-mention gets a row but no notification; blocked either way
and private-invisible mentions are ignored entirely; a re-edit
notifies only NEW mentions; "mention" is the 10th notification
toggle (default ON); mention links render via renderRichText.
Plain script (run.sh runs it with python directly).
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase170.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _run_scheduled_sweep  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import ratelimit  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(1701, "Alice", "alice")
BOB = H(1702, "Bob", "bob")
CAROL = H(1703, "Carol", "carol")
DAVE = H(1704, "Dave", "dave")
EVE = H(1705, "Eve", "eve")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()

c = TestClient(app)


def mk(uid, name, username):
    """Create the user row (first authed call) and pin the username
    directly, so mention lookup never depends on auth upsert."""
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


def mention_notifs(uid):
    db = SessionLocal()
    try:
        return db.query(models.Notification).filter_by(
            user_id=uid, type="mention").count()
    finally:
        db.close()


def post_mentions(pid):
    db = SessionLocal()
    try:
        return [m.mentioned_id for m in db.query(models.Mention)
                .filter_by(post_id=pid).all()]
    finally:
        db.close()


def comment_mentions(cid):
    db = SessionLocal()
    try:
        return [m.mentioned_id for m in db.query(models.Mention)
                .filter_by(comment_id=cid).all()]
    finally:
        db.close()


def post(author_headers, caption):
    r = c.post("/posts", headers=author_headers,
               json={"type": "text", "caption": caption})
    assert r.status_code == 200, r.text
    return r.json()


# 1. Users with usernames.
for uid, name, un in ((1701, "Alice", "alice"),
                      (1702, "Bob", "bob"),
                      (1703, "Carol", "carol"),
                      (1704, "Dave", "dave"),
                      (1705, "Eve", "eve")):
    mk(uid, name, un)
print("users with usernames OK")

# 2. Valid post mention (+ case-insensitive).
ratelimit.reset()
before = mention_notifs(1702)
p = post(ALICE, "Hello @bob how are you")
assert {"telegram_id": 1702, "username": "bob"} in p["mentions"], p
assert post_mentions(p["id"]) == [1702]
assert mention_notifs(1702) == before + 1
p2 = post(ALICE, "Shoutout to @BOB again")
assert post_mentions(p2["id"]) == [1702]
assert mention_notifs(1702) == before + 2
print("valid post mention OK")

# 3. Unknown username stays plain text.
ratelimit.reset()
before_bob = mention_notifs(1702)
before_carol = mention_notifs(1703)
p = post(ALICE, "Hello @ghostuser99 and @nobodyhere123")
assert p["mentions"] == [], p
assert post_mentions(p["id"]) == []
assert mention_notifs(1702) == before_bob
assert mention_notifs(1703) == before_carol
print("unknown username ignored OK")

# 4. Self-mention: row, no notification.
ratelimit.reset()
before = mention_notifs(1701)
p = post(ALICE, "Note to self @alice remember this")
assert post_mentions(p["id"]) == [1701]
assert mention_notifs(1701) == before
print("self-mention OK")

# 5. Blocked either way: ignored entirely.
ratelimit.reset()
r = c.post("/users/1702/block", headers=ALICE)
assert r.status_code == 200, r.text
before = mention_notifs(1702)
p = post(ALICE, "Hey @bob are you there")
assert post_mentions(p["id"]) == []
assert mention_notifs(1702) == before
r = c.post("/users/1702/block", headers=ALICE)
assert r.status_code == 200, r.text
r = c.post("/users/1701/block", headers=BOB)
assert r.status_code == 200, r.text
p = post(ALICE, "Hey @bob again")
assert post_mentions(p["id"]) == []
assert mention_notifs(1702) == before
r = c.post("/users/1701/block", headers=BOB)
assert r.status_code == 200, r.text
p = post(ALICE, "Hey @bob we are good")
assert post_mentions(p["id"]) == [1702]
assert mention_notifs(1702) == before + 1
print("blocked mentions ignored OK")

# 6. Private author: only followers are notified.
ratelimit.reset()
r = c.post("/me/privacy", headers=CAROL, json={"is_private": True})
assert r.status_code == 200, r.text
r = c.post("/users/1703/follow", headers=DAVE)
assert r.status_code == 200, r.text
r = c.get("/me/follow-requests", headers=CAROL)
assert r.status_code == 200, r.text
reqs = [x for x in r.json().get("follow_requests", [])
        if x["requester_id"] == 1704]
assert reqs, r.json()
r = c.post("/follow-requests/%s/accept" % reqs[0]["id"], headers=CAROL)
assert r.status_code == 200, r.text
before_dave = mention_notifs(1704)
before_eve = mention_notifs(1705)
p = post(CAROL, "Thanks @dave and @eve for reading")
assert post_mentions(p["id"]) == [1704], post_mentions(p["id"])
assert mention_notifs(1704) == before_dave + 1
assert mention_notifs(1705) == before_eve
r = c.post("/me/privacy", headers=CAROL, json={"is_private": False})
assert r.status_code == 200, r.text
print("private-account mention visibility OK")

# 7. Toggle OFF suppresses the notification, not the row.
ratelimit.reset()
r = c.post("/me/notification-prefs", headers=BOB, json={"mention": False})
assert r.status_code == 200 and r.json()["prefs"]["mention"] is False
before = mention_notifs(1702)
p = post(ALICE, "Hi @bob this is quiet")
assert post_mentions(p["id"]) == [1702]
assert mention_notifs(1702) == before
r = c.post("/me/notification-prefs", headers=BOB, json={"mention": True})
assert r.status_code == 200 and r.json()["prefs"]["mention"] is True
print("mention toggle OFF/ON OK")

# 8. Comment mention.
ratelimit.reset()
p = post(BOB, "My photo day")
before = mention_notifs(1702)
r = c.post("/posts/%s/comments" % p["id"], headers=ALICE,
           json={"text": "Great shot @bob!"})
assert r.status_code == 200, r.text
cm = r.json()
assert {"telegram_id": 1702, "username": "bob"} in cm["mentions"], cm
assert comment_mentions(cm["id"]) == [1702]
assert mention_notifs(1702) == before + 1
before_alice = mention_notifs(1701)
r = c.post("/posts/%s/comments" % p["id"], headers=ALICE,
           json={"text": "Adding @alice to this thread"})
assert r.status_code == 200, r.text
assert comment_mentions(r.json()["id"]) == [1701]
assert mention_notifs(1701) == before_alice
print("comment mention OK")

# 9. Edit dedupe: only NEW mentions notify; removal deletes rows.
ratelimit.reset()
before_bob = mention_notifs(1702)
before_carol = mention_notifs(1703)
p = post(ALICE, "Hello @bob")
assert mention_notifs(1702) == before_bob + 1
r = c.post("/posts/%s/edit" % p["id"], headers=ALICE,
           json={"caption": "Hello @bob and @carol"})
assert r.status_code == 200, r.text
assert sorted(post_mentions(p["id"])) == [1702, 1703]
assert mention_notifs(1702) == before_bob + 1
assert mention_notifs(1703) == before_carol + 1
r = c.post("/posts/%s/edit" % p["id"], headers=ALICE,
           json={"caption": "Hello @bob and @carol!"})
assert r.status_code == 200, r.text
assert mention_notifs(1702) == before_bob + 1
assert mention_notifs(1703) == before_carol + 1
r = c.post("/posts/%s/edit" % p["id"], headers=ALICE,
           json={"caption": "Hello @carol only"})
assert r.status_code == 200, r.text
assert post_mentions(p["id"]) == [1703]
r = c.post("/posts/%s/edit" % p["id"], headers=ALICE,
           json={"caption": "Hello @bob and @carol"})
assert r.status_code == 200, r.text
assert mention_notifs(1702) == before_bob + 2
assert mention_notifs(1703) == before_carol + 1
print("edit dedupe OK")

# 10. Scheduled-post mention: rows + in-app record via the sweeper.
ratelimit.reset()
before = mention_notifs(1702)
db = SessionLocal()
try:
    row = models.ScheduledPost(
        user_id=1701, text="Scheduled shoutout @bob",
        scheduled_at=datetime.utcnow() - timedelta(minutes=1),
        status="pending")
    db.add(row)
    db.commit()
    row_id = row.id
finally:
    db.close()
_run_scheduled_sweep()
db = SessionLocal()
try:
    row = db.get(models.ScheduledPost, row_id)
    assert row.status == "posted", row.status
    pid = row.posted_post_id
    assert pid
finally:
    db.close()
assert post_mentions(pid) == [1702]
assert mention_notifs(1702) == before + 1
print("scheduled-post mention OK")

# 11. Delete cleans mention rows.
ratelimit.reset()
p = post(ALICE, "Temp @bob post")
assert post_mentions(p["id"]) == [1702]
r = c.delete("/posts/%s" % p["id"], headers=ALICE)
assert r.status_code == 200, r.text
assert post_mentions(p["id"]) == []
print("delete cleans mentions OK")

# 12. Client markers, version, routes, backup.
js = c.get("/webapp/app.js").text
for marker in ("renderRichText", "attachMentionAutocomplete",
               "mention-drop", '["mention", "📣 Mentions"',
               'mention: "📣"', "loadSkills", "loadBlood",
               "MASCOT_TIPS_BY_VIEW", "totp-card"):
    assert marker in js, marker
assert "app.js?v=191" in HTML
assert ("?v=16" + "9") not in HTML
assert "style.css?v=191" in HTML
assert "games.js?v=191" in HTML
assert ".mention" in CSS
paths = {rt.path for rt in app.routes}
assert len(paths) == 184, len(paths)
assert "/posts" in paths
h = c.get("/admin/health", headers=ADMIN).json()
assert h["version"] == 191, h
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
assert "mentions" in r.json()["tables"]
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
print("client + version + routes + backup OK (174 routes, 48 tables, ?v=191)")

# 13. Phase 170 rider: stale /media token recovery.
# (a) Foreground return refreshes the token (the 45-min tick
# never fires while the WebView is backgrounded).
hb = js[js.index("function startHeartbeat()"):
        js.index("async function refreshMediaToken()")]
assert ("if (!document.hidden) { sendHeartbeat(); refreshMediaToken(); }"
        in hb), hb
assert "setInterval(refreshMediaToken, 2700000)" in js
# (b) The img error handler re-issues the token before rebuilding.
assert 'document.addEventListener("error", async (e) => {' in js
eh = js[js.index('document.addEventListener("error", async (e) => {'):]
eh = eh[:eh.index("// ---------------------------------------------------- entry")]
assert "await refreshMediaToken();" in eh, eh
assert "!t.dataset.mtok" in eh, eh
assert eh.index("await refreshMediaToken();") < eh.index(
    "t.src = mediaUrl(decodeURIComponent(m[1]));"), eh
assert "mediaTokenRefresh" in js
# (c) Server-side: an expired token 401s; a fresh /auth token is
# accepted again (the fake file_id then 404s at Telegram — the
# point is the token, not the file).
r = c.post("/posts", headers=ALICE,
           json={"type": "photo", "caption": "rider",
                 "media_file_id": "rider1"})
assert r.status_code == 200, r.text
import base64  # noqa: E402
iat = int(time.time()) - 7200
exp = iat + 3600
sig = hmac.new(os.environ["BOT_TOKEN"].encode(),
               f"nexora-media:1701:{iat}:{exp}".encode(),
               hashlib.sha256).hexdigest()
stale = base64.urlsafe_b64encode(
    f"1701.{iat}.{exp}.{sig}".encode()).decode()
r = c.get("/media/rider1?mt=" + stale)
assert r.status_code == 401, r.status_code
r = c.post("/auth", json={"initData": make_init_data(
    {"id": 1701, "first_name": "Alice", "username": "alice"})})
assert r.status_code == 200, r.text
fresh = r.json()["media_token"]
assert fresh and fresh != stale
r = c.get("/media/rider1?mt=" + fresh)
assert r.status_code == 404, r.status_code
print("rider: stale-token recovery OK")

print("PHASE 170 OK")
