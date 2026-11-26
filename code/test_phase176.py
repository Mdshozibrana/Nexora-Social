"""Phase 176 tests: Public post link.

GET /p/{post_id} serves a public HTML page (no auth) with Open
Graph meta + the post content + an "Open in Nexora" button.
GET /posts/{id}/share-link returns the URL. Privacy: deleted
posts 404; private-account posts show only the generic notice;
when the opener is identified (X-Init-Data) a post by an author
who blocked that viewer also shows only the notice. The page
never leaks media, counts, comments or usernames.
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase176.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402


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


ALICE = H(1761, "Alice", "alice")
BOB = H(1762, "Bob", "bob")
CAROL = H(1763, "Carol", "carol")
DAVE = H(1764, "Dave", "dave")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
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


for uid, name, uname in ((1761, "Alice", "alice"), (1762, "Bob", "bob"),
                         (1763, "Carol", "carol"), (1764, "Dave", "dave")):
    mk(uid, name, uname)


def mkpost(headers, caption):
    r = c.post("/posts", json={"type": "text", "caption": caption},
               headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# 1. Public page: OG meta + content + Open in Nexora button, no leaks.
p1 = mkpost(ALICE, "A public post about sunrise coffee")
r = c.get(f"/p/{p1}")
assert r.status_code == 200, r.text
body = r.text
assert "A public post about sunrise coffee" in body, body
assert 'property="og:title"' in body, body
assert 'property="og:description"' in body, body
assert "og-image.png" in body, body
assert 'property="og:url"' in body and f"/p/{p1}" in body, body
assert "Open in Nexora" in body, body
assert "t.me/NexoraSocial_bot?start=post_" in body, body
assert "Alice on Nexora Social" in body, body
# No API data beyond the single post: no username, no counts, no comments.
assert "@alice" not in body, body  # no @username anywhere
assert "comments" not in body.lower(), body
assert "followers" not in body.lower(), body
assert '"id":' not in body, body
print("1. public page renders OG + content OK")

# 2. HTML escaping: markup in the caption is escaped, never rendered.
px = mkpost(BOB, "<script>alert(1)</script> plain words")
r = c.get(f"/p/{px}")
assert r.status_code == 200, r.text
assert "<script>alert(1)</script>" not in r.text, r.text
assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text, r.text
assert "plain words" in r.text, r.text
print("2. escaping OK")

# 3. Deleted post -> 404; share-link for it -> 404.
pd = mkpost(DAVE, "Dave post to delete")
r = c.delete(f"/posts/{pd}", headers=DAVE)
assert r.status_code == 200, r.text
r = c.get(f"/p/{pd}")
assert r.status_code == 404, r.text
assert "Post not found" in r.text, r.text
r = c.get(f"/posts/{pd}/share-link", headers=DAVE)
assert r.status_code == 404, r.text
print("3. deleted -> 404 OK")

# 4. Private account: anonymous sees only the notice; the author
# still sees the full page; share-link is 403 for a non-follower.
pc = mkpost(CAROL, "Carol private diary entry")
r = c.post("/me/privacy", json={"is_private": True}, headers=CAROL)
assert r.status_code == 200, r.text
r = c.get(f"/p/{pc}")
assert r.status_code == 200, r.text
assert "This post isn't public." in r.text, r.text
assert "Carol private diary entry" not in r.text, r.text
assert "carol" not in r.text.lower(), r.text
r = c.get(f"/p/{pc}", headers=CAROL)
assert r.status_code == 200, r.text
assert "Carol private diary entry" in r.text, r.text
r = c.get(f"/posts/{pc}/share-link", headers=ALICE)
assert r.status_code == 403, r.text
r = c.post("/me/privacy", json={"is_private": False}, headers=CAROL)
assert r.status_code == 200, r.text
r = c.get(f"/p/{pc}")
assert "Carol private diary entry" in r.text, r.text
print("4. private -> notice OK")

# 5. Blocked author: the blocked viewer (identified) sees only the
# notice; an anonymous opener and an unblocked member see the page.
pb = mkpost(BOB, "Bob post Alice must not see")
r = c.post("/users/1761/block", headers=BOB)
assert r.status_code == 200, r.text
r = c.get(f"/p/{pb}", headers=ALICE)
assert r.status_code == 200, r.text
assert "This post isn't public." in r.text, r.text
assert "Bob post Alice must not see" not in r.text, r.text
assert "bob" not in r.text.lower(), r.text
r = c.get(f"/p/{pb}")
assert r.status_code == 200, r.text
assert "Bob post Alice must not see" in r.text, r.text
r = c.get(f"/p/{pb}", headers=CAROL)
assert "Bob post Alice must not see" in r.text, r.text
print("5. blocked author -> notice for the blocked viewer OK")

# 6. Repost link resolves to the original post.
# Bob blocked Alice in §5, so he cannot repost her post;
# Carol reposts it instead.
r = c.post(f"/posts/{p1}/repost", headers=CAROL)
assert r.status_code == 200, r.text
assert r.json()["reposted"] is True, r.text
db = SessionLocal()
try:
    row = db.query(models.Post).filter_by(
        user_id=1763, repost_of_id=p1).first()
    assert row is not None, "repost row missing"
    rp = row.id
finally:
    db.close()
r = c.get(f"/p/{rp}")
assert r.status_code == 200, r.text
assert "A public post about sunrise coffee" in r.text, r.text
print("6. repost resolves to original OK")

# 7. share-link: returns the URL; no auth -> 401.
r = c.get(f"/posts/{p1}/share-link", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["share_link"] == f"/p/{p1}", r.text
r = c.get(f"/posts/{p1}/share-link")
assert r.status_code == 401, r.text
r = c.get("/posts/999999/share-link", headers=ALICE)
assert r.status_code == 404, r.text
print("7. share-link OK")

# 8. Client markers, version, routes, backup tables.
assert "Copy public link" in JS, "missing Copy public link row"
assert "share-link" in JS, "missing share-link call"
assert HTML.count("?v=187") == 10, HTML.count("?v=187")
assert "?v=17" + "5" not in HTML
assert "/?v=187" in BOT and "/?v=17" + "5" not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
# 2 new unique paths this phase.
assert len(paths) == 183, len(paths)
for want in ("/p/{post_id}", "/posts/{post_id}/share-link"):
    assert want in paths, want
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
b = r.json()
assert len(b["tables"]) == 52, len(b["tables"])
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
print("8. client + version + routes + backup OK")

print("PHASE 176 OK")
