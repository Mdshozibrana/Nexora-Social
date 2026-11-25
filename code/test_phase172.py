"""Phase 172 tests: Story Highlights.

POST /highlights pins the member's own stories (active AND expired)
into named collections (max 20/user, max 50 stories each); GET
/highlights/user/{uid} lists them (private/blocked viewers see []);
GET /highlights/{hid} replays the stories in position order;
rename / delete / add-stories / remove-story are owner-only.
Expired stories are never deleted — the strip only filters them —
so a highlight can include them, and _media_visible lets an expired
story load ONLY inside a highlight the viewer may see. Deleting a
story drops it from every highlight. Plain script (run.sh runs it
with python directly).
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase172.db"
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


ALICE = H(1721, "Alice", "alice")
BOB = H(1722, "Bob", "bob")
CAROL = H(1723, "Carol", "carol")
DAVE = H(1724, "Dave", "dave")
EVE = H(1725, "Eve", "eve")
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


def mkstory(uid, file_id, hours_old=0):
    db = SessionLocal()
    try:
        s = models.Story(user_id=uid, media_file_id=file_id,
                         created_at=datetime.utcnow() - timedelta(hours=hours_old))
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def follow(a, b):
    db = SessionLocal()
    try:
        if db.query(models.Follow).filter_by(
                follower_id=a, following_id=b).first() is None:
            db.add(models.Follow(follower_id=a, following_id=b))
            db.commit()
    finally:
        db.close()


def set_private(uid, private=True):
    db = SessionLocal()
    try:
        u = db.get(models.User, uid)
        u.is_private = private
        db.commit()
    finally:
        db.close()


def block(a, b):
    db = SessionLocal()
    try:
        if db.query(models.UserBlock).filter_by(
                blocker_id=a, blocked_id=b).first() is None:
            db.add(models.UserBlock(blocker_id=a, blocked_id=b))
            db.commit()
    finally:
        db.close()


def highlight_count(uid):
    db = SessionLocal()
    try:
        return db.query(models.StoryHighlight).filter_by(
            user_id=uid).count()
    finally:
        db.close()


for uid, name, uname in ((1721, "Alice", "alice"), (1722, "Bob", "bob"),
                         (1723, "Carol", "carol"), (1724, "Dave", "dave"),
                         (1725, "Eve", "eve")):
    mk(uid, name, uname)

# 1. Create with an expired story included; list + detail round-trip.
s1 = mkstory(1721, "hl_file_live")
s2 = mkstory(1721, "hl_file_old", hours_old=25)
r = c.post("/highlights", headers=ALICE,
           json={"title": "Trips", "story_ids": [s1, s2]})
assert r.status_code == 200, r.text
h = r.json()
assert h["story_count"] == 2, h
assert h["cover_media_file_id"] == "hl_file_live", h
assert h["title"] == "Trips" and h["user_id"] == 1721, h
hid = h["id"]
r = c.get("/highlights/user/1721", headers=ALICE)
assert r.status_code == 200, r.text
assert len(r.json()["highlights"]) == 1, r.text
r = c.get(f"/highlights/{hid}", headers=ALICE)
assert r.status_code == 200, r.text
d = r.json()
assert [s["id"] for s in d["stories"]] == [s1, s2], d
assert d["stories"][0]["expired"] is False, d
assert d["stories"][1]["expired"] is True, d
assert d["owner"]["telegram_id"] == 1721, d
print("1. create/list/detail with expired story OK")

# 2. /stories/mine returns active AND expired, newest first.
r = c.get("/stories/mine", headers=ALICE)
assert r.status_code == 200, r.text
mine = r.json()["stories"]
assert [s["id"] for s in mine] == [s2, s1], mine
assert mine[0]["expired"] is True and mine[1]["expired"] is False, mine
r = c.get("/stories/mine", headers=BOB)
assert r.json()["stories"] == [], r.text
print("2. /stories/mine OK")

# 3. Validation: empty title, no stories, other's story, >50 stories.
r = c.post("/highlights", headers=ALICE,
           json={"title": "  ", "story_ids": [s1]})
assert r.status_code == 400, r.text
r = c.post("/highlights", headers=ALICE,
           json={"title": "X", "story_ids": []})
assert r.status_code == 400, r.text
s_bob = mkstory(1722, "hl_file_bob")
r = c.post("/highlights", headers=ALICE,
           json={"title": "X", "story_ids": [s_bob]})
assert r.status_code == 400, r.text
r = c.post("/highlights", headers=ALICE,
           json={"title": "X", "story_ids": list(range(1, 52))})
assert r.status_code == 400, r.text
print("3. validation OK")

# 4. Privacy: private author hides highlights from strangers.
set_private(1721, True)
r = c.get("/highlights/user/1721", headers=BOB)
assert r.json()["highlights"] == [], r.text
r = c.get(f"/highlights/{hid}", headers=BOB)
assert r.status_code == 404, r.text
follow(1722, 1721)
r = c.get("/highlights/user/1721", headers=BOB)
assert len(r.json()["highlights"]) == 1, r.text
r = c.get(f"/highlights/{hid}", headers=BOB)
assert r.status_code == 200, r.text
set_private(1721, False)
print("4. private-account visibility OK")

# 5. Block hides highlights both directions.
block(1722, 1721)
r = c.get("/highlights/user/1721", headers=BOB)
assert r.json()["highlights"] == [], r.text
r = c.get(f"/highlights/{hid}", headers=BOB)
assert r.status_code == 404, r.text
db = SessionLocal()
db.query(models.UserBlock).filter_by(blocker_id=1722).delete()
db.commit()
db.close()
print("5. block visibility OK")

# 6. Non-owner cannot manage; owner rename/add/remove/delete.
r = c.post(f"/highlights/{hid}/rename", headers=BOB,
           json={"title": "Hijack"})
assert r.status_code == 403, r.text
r = c.delete(f"/highlights/{hid}", headers=BOB)
assert r.status_code == 403, r.text
r = c.post(f"/highlights/{hid}/stories", headers=BOB,
           json={"story_ids": [s1]})
assert r.status_code == 403, r.text
r = c.delete(f"/highlights/{hid}/stories/{s1}", headers=BOB)
assert r.status_code == 403, r.text
r = c.post(f"/highlights/{hid}/rename", headers=ALICE,
           json={"title": "  "})
assert r.status_code == 400, r.text
r = c.post(f"/highlights/{hid}/rename", headers=ALICE,
           json={"title": "Journeys"})
assert r.status_code == 200 and r.json()["title"] == "Journeys", r.text
s3 = mkstory(1721, "hl_file_new")
r = c.post(f"/highlights/{hid}/stories", headers=ALICE,
           json={"story_ids": [s3, s3, s1]})
assert r.status_code == 200, r.text
assert r.json()["story_count"] == 3, r.text  # s1 deduped
r = c.delete(f"/highlights/{hid}/stories/{s3}", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get(f"/highlights/{hid}", headers=ALICE)
assert [s["id"] for s in r.json()["stories"]] == [s1, s2], r.text
print("6. owner management OK")

# 7. Expired-story media: visible only inside a visible highlight.
from app.main import _media_visible  # noqa: E402
db = SessionLocal()
try:
    assert _media_visible(db, 1722, "hl_file_old") is True
    assert _media_visible(db, 1722, "hl_file_live") is True
    s_orphan = mkstory(1721, "hl_file_orphan", hours_old=30)
    assert _media_visible(db, 1722, "hl_file_orphan") is False
    set_private(1721, True)
    assert _media_visible(db, 1723, "hl_file_old") is False  # stranger
    assert _media_visible(db, 1722, "hl_file_old") is True  # follower
    set_private(1721, False)
finally:
    db.close()
print("7. expired-story media visibility OK")

# 8. Deleting a story drops it from the highlight; stories survive
#    highlight deletion.
r = c.delete(f"/stories/{s2}", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get(f"/highlights/{hid}", headers=ALICE)
assert [s["id"] for s in r.json()["stories"]] == [s1], r.text
r = c.delete(f"/highlights/{hid}", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get(f"/highlights/{hid}", headers=ALICE)
assert r.status_code == 404, r.text
r = c.get("/stories/mine", headers=ALICE)
assert s1 in [s["id"] for s in r.json()["stories"]], r.text
print("8. delete cleanup OK")

# 9. Cap: 20 highlights per user.
db = SessionLocal()
try:
    for i in range(19):
        db.add(models.StoryHighlight(user_id=1724, title=f"H{i}"))
    db.commit()
finally:
    db.close()
assert highlight_count(1724) == 19
r = c.post("/highlights", headers=DAVE,
           json={"title": "Last", "story_ids": [mkstory(1724, "hl_d")]})
assert r.status_code == 200, r.text
r = c.post("/highlights", headers=DAVE,
           json={"title": "Over", "story_ids": [mkstory(1724, "hl_d2")]})
assert r.status_code == 400, r.text
print("9. 20-highlight cap OK")

# 10. Client markers, version, routes, backup.
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
for marker in ("hl-row", "hlCircle", "loadHighlights", "openHighlight",
               "openHighlightPicker", "closeHighlightPicker", "hlMode",
               "hl-picker", "/highlights/user/", "/stories/mine",
               "profile-highlights", "loadSkills", "loadBlood",
               "MASCOT_TIPS_BY_VIEW", "totp-card"):
    assert marker in JS, marker
for marker in (".hl-row", ".hl-ring", ".hl-label", ".hl-pick-grid",
               ".hl-sheet", ".hl-picker-overlay"):
    assert marker in CSS, marker
assert "app.js?v=184" in HTML
assert ("?v=17" + "1") not in HTML
assert "style.css?v=184" in HTML
paths = {rt.path for rt in app.routes}
assert len(paths) == 183, len(paths)
for p in ("/highlights", "/highlights/user/{user_id}",
          "/highlights/{hid}", "/stories/mine"):
    assert p in paths, p
h = c.get("/admin/health", headers=ADMIN).json()
assert h["version"] == 184, h
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
assert "story_highlights" in r.json()["tables"]
assert "highlight_stories" in r.json()["tables"]
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
print("client + version + routes + backup OK (174 routes, 48 tables, ?v=184)")

print("PHASE 172 OK")
