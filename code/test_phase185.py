"""Phase 185 tests: second follow-request accept/reject 500 + DELETE
/admin/fake-users/{id} rate limit + run.sh versioning.

1. Second follow-request accept: A requests to follow private B, B
   accepts (200), A unfollows, A requests again, B accepts again —
   the second accept must succeed cleanly. Before the fix it 500'd:
   the first accept left an "accepted" row behind, and flipping the
   second request to "accepted" hit the follow_requests unique key
   (requester_id, target_id, status). The fix clears the stale
   decided row for the pair when a decision is made, so at most one
   row per (pair, outcome) ever exists.
2. Same stale-row hazard on the decline path: request -> reject ->
   request -> reject — the second reject must also be a clean 200,
   and neither rejected request may leave a follow row behind.
3. DELETE /admin/fake-users/{id} joins the shared admin_mutation
   bucket (120/h, Phase 181): 120 deletes -> 200 each, the 121st
   -> 429 with Retry-After, admin GETs unaffected, and after a
   reset the endpoint works again (proving the 429 was the bucket,
   not a broken endpoint). The delete still wipes the managed
   account completely (Phase 24 semantics, unchanged).
4. Version + routes + backup pins: shell ?v=185 (x10), bot menu
   /?v=185, ?v=185 gone from the shell, 183 routes, 52 backup
   tables, /admin/health version 185.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase185.db"
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
from app import ratelimit  # noqa: E402
from app.db import SessionLocal  # noqa: E402


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


ALICE = H(1851, "Alice", "alice185")
BOB = H(1852, "Bob", "bob185")
CAROL = H(1853, "Carol", "carol185")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()

c = TestClient(app, raise_server_exceptions=False)


def mk(uid, name, username):
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text


for uid, name, uname in ((1851, "Alice", "alice185"),
                         (1852, "Bob", "bob185"),
                         (1853, "Carol", "carol185")):
    mk(uid, name, uname)


def set_private(headers, value):
    r = c.post("/me/privacy", json={"is_private": value}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["is_private"]


def request_follow(requester_h, target_uid):
    r = c.post(f"/users/{target_uid}/follow", headers=requester_h)
    assert r.status_code == 200, r.text
    assert r.json()["requested"] is True, r.json()
    return r.json()


def pending_requests(target_h):
    r = c.get("/me/follow-requests", headers=target_h)
    assert r.status_code == 200, r.text
    return r.json()["follow_requests"]


def is_following(follower_id, following_id):
    db = SessionLocal()
    try:
        return db.query(models.Follow).filter_by(
            follower_id=follower_id, following_id=following_id).first() \
            is not None
    finally:
        db.close()


def request_rows(requester_id, target_id):
    db = SessionLocal()
    try:
        return [(r.id, r.status) for r in db.query(models.FollowRequest)
                .filter_by(requester_id=requester_id,
                           target_id=target_id).all()]
    finally:
        db.close()


# --- 1. Second accept for the same pair must not 500 -----------------------
assert set_private(BOB, True) is True
request_follow(ALICE, 1852)
rows = pending_requests(BOB)
assert len(rows) == 1, rows
r = c.post(f"/follow-requests/{rows[0]['id']}/accept", headers=BOB)
assert r.status_code == 200, r.text
assert r.json()["accepted"] is True, r.json()
assert is_following(1851, 1852) is True
assert pending_requests(BOB) == []
# Alice unfollows, then asks again.
r = c.post("/users/1852/follow", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["following"] is False, r.json()
assert is_following(1851, 1852) is False
request_follow(ALICE, 1852)
rows = pending_requests(BOB)
assert len(rows) == 1, rows
r = c.post(f"/follow-requests/{rows[0]['id']}/accept", headers=BOB)
assert r.status_code == 200, r.text
assert r.json()["accepted"] is True, r.json()
assert is_following(1851, 1852) is True
assert pending_requests(BOB) == []
# No duplicate follow rows, and exactly one decided row survives.
db = SessionLocal()
try:
    assert db.query(models.Follow).filter_by(
        follower_id=1851, following_id=1852).count() == 1
finally:
    db.close()
assert [s for _, s in request_rows(1851, 1852)] == ["accepted"], \
    request_rows(1851, 1852)
print("1. second follow-request accept OK (was 500)")

# --- 2. Second reject for the same pair must not 500 -----------------------
request_follow(CAROL, 1852)
rows = pending_requests(BOB)
assert len(rows) == 1, rows
r = c.post(f"/follow-requests/{rows[0]['id']}/reject", headers=BOB)
assert r.status_code == 200, r.text
assert r.json()["rejected"] is True, r.json()
assert is_following(1853, 1852) is False
request_follow(CAROL, 1852)
rows = pending_requests(BOB)
assert len(rows) == 1, rows
r = c.post(f"/follow-requests/{rows[0]['id']}/reject", headers=BOB)
assert r.status_code == 200, r.text
assert r.json()["rejected"] is True, r.json()
assert is_following(1853, 1852) is False
assert [s for _, s in request_rows(1853, 1852)] == ["rejected"], \
    request_rows(1853, 1852)
print("2. second follow-request reject OK (same stale-row hazard)")

# --- 3. DELETE /admin/fake-users/{id} shares admin_mutation (120/h) --------
# Seed 121 managed accounts straight into the DB (bypassing the
# HTTP create endpoint, which draws from the same bucket).
db = SessionLocal()
try:
    for i in range(121):
        db.add(models.User(telegram_id=9000000185 + i,
                           first_name=f"Fake185-{i}",
                           is_managed=True))
    db.commit()
finally:
    db.close()
ratelimit.reset()
for i in range(120):
    r = c.delete(f"/admin/fake-users/{9000000185 + i}", headers=ADMIN)
    assert r.status_code == 200, (i, r.status_code, r.text)
    assert r.json()["deleted"] == 9000000185 + i, r.json()
# The 121st mutation in the hour is refused, like its siblings.
r = c.delete("/admin/fake-users/9000000305", headers=ADMIN)
assert r.status_code == 429, (r.status_code, r.text)
assert "Retry-After" in r.headers, r.headers
# The refused delete left its target untouched.
db = SessionLocal()
try:
    assert db.get(models.User, 9000000305) is not None
finally:
    db.close()
# Admin GETs are unaffected by the mutation budget.
r = c.get("/admin/health", headers=ADMIN)
assert r.status_code == 200, r.text
# After a reset the endpoint works again — the 429 was the bucket.
ratelimit.reset()
r = c.delete("/admin/fake-users/9000000305", headers=ADMIN)
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    assert db.get(models.User, 9000000305) is None
finally:
    db.close()
print("3. DELETE /admin/fake-users/{id} rate-limited in admin_mutation OK")

# --- 4. Version + routes + backup pins --------------------------------------
assert HTML.count("?v=185") == 10, HTML.count("?v=185")
assert "?v=18" + "4" not in HTML
assert "/?v=185" in BOT and "/?v=18" + "4" not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 183, len(paths)
assert "/admin/fake-users/{telegram_id}" in paths
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
r = c.get("/admin/health", headers=ADMIN)
assert r.json()["version"] == 185, r.json()
print("4. version ?v=185 + routes 183 + backup 52 OK")

print("PHASE 185 OK")
