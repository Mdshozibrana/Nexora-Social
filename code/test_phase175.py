"""Phase 175 tests: Saved collections.

POST /saved/collections creates a named folder (max 20,
name 1-50 chars, unique per member); GET lists them
(with ?post_id=N membership flags); GET one returns
its posts; PATCH renames; DELETE removes only the
folder; POST/DELETE .../posts adds/removes (add also
bookmarks; dupe add is a no-op; remove never unsaves;
unsave drops the post from all collections).
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase175.db"
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


ALICE = H(1751, "Alice", "alice")
BOB = H(1752, "Bob", "bob")
CAROL = H(1753, "Carol", "carol")
DAVE = H(1754, "Dave", "dave")
EVE = H(1755, "Eve", "eve")
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


for uid, name, uname in ((1751, "Alice", "alice"), (1752, "Bob", "bob"),
                         (1753, "Carol", "carol"), (1754, "Dave", "dave"),
                         (1755, "Eve", "eve")):
    mk(uid, name, uname)




# --- collections test helpers ------------------------------------------------


def mkpost(headers, caption):
    r = c.post("/posts", json={"type": "text", "caption": caption},
               headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def mkcoll(headers, name):
    r = c.post("/saved/collections", json={"name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def saved_ids(headers):
    r = c.get("/me/saved", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


def coll_post_ids(headers, cid):
    r = c.get(f"/saved/collections/{cid}", headers=headers)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["posts"]]


# 1. Create / list / rename / delete + name + cap rules.
c1 = mkcoll(ALICE, "Tech")
r = c.get("/saved/collections", headers=ALICE)
assert r.status_code == 200, r.text
assert [x["name"] for x in r.json()["collections"]] == ["Tech"], r.text
assert r.json()["collections"][0]["post_count"] == 0, r.text
r = c.post("/saved/collections", json={"name": "tech"}, headers=ALICE)
assert r.status_code == 400, r.text
r = c.post("/saved/collections", json={"name": "   "}, headers=ALICE)
assert r.status_code == 400, r.text
# Over-long names are rejected by request validation (422) before
# the handler runs; empty names reach the handler and get a 400.
r = c.post("/saved/collections", json={"name": "x" * 51}, headers=ALICE)
assert r.status_code == 422, r.text
r = c.patch(f"/saved/collections/{c1}", json={"name": "Reading"},
            headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["name"] == "Reading", r.text
c2 = mkcoll(ALICE, "Other")
r = c.patch(f"/saved/collections/{c1}", json={"name": "Other"},
            headers=ALICE)
assert r.status_code == 400, r.text
r = c.patch(f"/saved/collections/{c1}", json={"name": "  "}, headers=ALICE)
assert r.status_code == 400, r.text
# Non-owner: another member's collection looks missing.
r = c.get(f"/saved/collections/{c1}", headers=BOB)
assert r.status_code == 404, r.text
r = c.patch(f"/saved/collections/{c1}", json={"name": "Nope"}, headers=BOB)
assert r.status_code == 404, r.text
r = c.delete(f"/saved/collections/{c1}", headers=BOB)
assert r.status_code == 404, r.text
r = c.delete(f"/saved/collections/{c2}", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["deleted"] is True, r.text
r = c.get("/saved/collections", headers=ALICE)
assert [x["name"] for x in r.json()["collections"]] == ["Reading"], r.text
# Cap: 20 per member (Dave starts empty).
for i in range(20):
    mkcoll(DAVE, f"Dave {i}")
r = c.post("/saved/collections", json={"name": "Dave 21"}, headers=DAVE)
assert r.status_code == 400, r.text
print("1. create/list/rename/delete + rules OK")

# 2. Add (auto-bookmarks) / duplicate no-op / move / remove.
p1 = mkpost(BOB, "Bob's post for collections")
r = c.post(f"/saved/collections/{c1}/posts", json={"post_id": p1},
           headers=ALICE)
assert r.status_code == 200, r.text
assert r.json() == {"added": True, "saved": True}, r.text
assert p1 in saved_ids(ALICE)
assert p1 in coll_post_ids(ALICE, c1)
r = c.post(f"/saved/collections/{c1}/posts", json={"post_id": p1},
           headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["added"] is False, r.text
c3 = mkcoll(ALICE, "Second")
r = c.get(f"/saved/collections?post_id={p1}", headers=ALICE)
assert r.status_code == 200, r.text
flags = {x["name"]: x["has_post"] for x in r.json()["collections"]}
assert flags == {"Reading": True, "Second": False}, flags
# Move: add to Second, remove from Reading.
r = c.post(f"/saved/collections/{c3}/posts", json={"post_id": p1},
           headers=ALICE)
assert r.json()["added"] is True, r.text
r = c.delete(f"/saved/collections/{c1}/posts/{p1}", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["removed"] is True, r.text
assert p1 not in coll_post_ids(ALICE, c1)
assert p1 in coll_post_ids(ALICE, c3)
assert p1 in saved_ids(ALICE)
r = c.delete(f"/saved/collections/{c1}/posts/{p1}", headers=ALICE)
assert r.json()["removed"] is False, r.text
print("2. add/move/remove OK")

# 3. Unsaving drops the post from every collection.
r = c.post(f"/posts/{p1}/save", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["saved"] is False, r.text
assert p1 not in coll_post_ids(ALICE, c3)
assert p1 not in saved_ids(ALICE)
print("3. unsave cascade OK")

# 4. Deleting a collection leaves its posts in All saved.
p2 = mkpost(CAROL, "Carol's post for collections")
r = c.post(f"/posts/{p2}/save", headers=ALICE)
assert r.json()["saved"] is True, r.text
r = c.post(f"/saved/collections/{c3}/posts", json={"post_id": p2},
           headers=ALICE)
assert r.json()["added"] is True, r.text
r = c.delete(f"/saved/collections/{c3}", headers=ALICE)
assert r.status_code == 200, r.text
assert p2 in saved_ids(ALICE)
r = c.get("/saved/collections", headers=ALICE)
assert [x["name"] for x in r.json()["collections"]] == ["Reading"], r.text
print("4. delete collection keeps posts OK")

# 5. Isolation + bad targets.
r = c.get("/saved/collections", headers=BOB)
assert r.json()["collections"] == [], r.text
r = c.post(f"/saved/collections/{c1}/posts", json={"post_id": 999999},
           headers=ALICE)
assert r.status_code == 404, r.text
r = c.post(f"/saved/collections/{c1}/posts", json={"post_id": p2},
           headers=BOB)
assert r.status_code == 404, r.text
r = c.delete(f"/saved/collections/{c1}/posts/{p2}", headers=BOB)
assert r.status_code == 404, r.text
print("5. isolation + bad targets OK")

# 6. Client markers, version, routes, backup tables.
JS_MARKS = ["savedCollectionOpen", "loadSavedCollections",
            "openSaveToCollection", "Save to collection",
            "saved-collections", "saved-chip", "saved-coll-head",
            "New collection", "saved-new-row"]
for m in JS_MARKS:
    assert m in JS, f"missing JS marker: {m}"
assert 'id="saved-collections"' in HTML
assert ".saved-collections" in CSS and ".saved-chip" in CSS
assert HTML.count("?v=182") == 10, HTML.count("?v=182")
assert "?v=17" + "4" not in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert "/?v=182" in BOT and "/?v=17" + "4" not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
# 7 endpoints, 4 new unique paths (methods share paths).
assert len(paths) == 183, len(paths)
for want in ("/saved/collections", "/saved/collections/{cid}",
             "/saved/collections/{cid}/posts",
             "/saved/collections/{cid}/posts/{post_id}"):
    assert want in paths, want
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
b = r.json()
assert len(b["tables"]) == 52, len(b["tables"])
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
print("6. client + version + routes + backup OK")

print("PHASE 175 OK")
