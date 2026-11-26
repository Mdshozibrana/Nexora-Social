"""Phase 182 tests: Blood & community — audit H12/H13/M20/M21/L15/L16/L17/L18/L20.

H12 — respond: blocked either way (author blocked responder, or
  responder blocked author) -> 403, no blood_respond notification;
  private author + non-follower -> 403, no notification; follower
  of a private author -> 200; a NON-donor may still respond.
H13 — create rejects phone-like contact (Latin + Bengali digits,
  with +/spaces/dashes/parens) with the 400 message; "DM me",
  "ward 3", "bed 12", dates still pass; a phone-like contact
  stored before the fix never renders on read (masked to "").
M20 — skill directory / blood directory / search users exclude
  banned members; Skill Connect to a banned member -> 403 and no
  notification (connect to a clean member still works).
L15 — muted authors hidden from search users, suggested users,
  leaderboard (top-50 + the outsider "me" rank), skill directory,
  blood directory, blood requests, Nearby and notifications (list
  + unread count). DMs untouched: a DM from the muted author still
  delivers and the thread still reads.
L16 — Nearby hides private non-followed members (a follower still
  sees them on the map).
L17 — routing URL uses the foot profile, not driving.
L18 — nbFetchTimeout wires a real AbortController.
M21 — Street View: 401/403 -> an honest "couldn't load" message
  distinct from "No street-level photo here yet."; the lookup
  budget totals ~9 s (constants + no second 8 s attempt); the 10 s
  viewer race is unchanged.
L20 — _fuzz offset identical across calls (no date in the seed)
  and still 50-100 m; different members get different offsets.
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import math
import os
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase182.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.notify as notify_mod  # noqa: E402

SENT = []


async def fake_send(chat_id, text):
    SENT.append((chat_id, text))
    return True


notify_mod.send_message = fake_send

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _fuzz, _looks_phone_like  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import ratelimit  # noqa: E402


def make_init_data(user, auth_date=None):
    import time
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


ALICE = H(1821, "Alice", "alice182")
BOB = H(1822, "Bob", "bob182")
CAROL = H(1823, "Carol", "carol182")
DAVE = H(1824, "Dave", "dave182")
EVE = H(1825, "Eve", "eve182")
FRANK = H(1826, "Frank", "frank182")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
MAIN = open(os.path.join(ROOT, "code/app/main.py")).read()

c = TestClient(app)


def mk(uid, name, username):
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        u = db.get(models.User, uid)
        assert u is not None, "user %s not created" % uid
        u.username = username
        db.commit()


for uid, name, uname in ((1821, "Alice", "alice182"),
                         (1822, "Bob", "bob182"),
                         (1823, "Carol", "carol182"),
                         (1824, "Dave", "dave182"),
                         (1825, "Eve", "eve182"),
                         (1826, "Frank", "frank182")):
    mk(uid, name, uname)


def blood_responds(uid):
    with SessionLocal() as db:
        return db.query(models.Notification).filter_by(
            user_id=uid, type="blood_respond").count()


def notif_rows(uid, ntype=None):
    with SessionLocal() as db:
        q = db.query(models.Notification).filter_by(user_id=uid)
        if ntype:
            q = q.filter_by(type=ntype)
        return [(n.type, n.actor_id, n.is_read)
                for n in q.order_by(models.Notification.id).all()]


def set_private(uid, private=True):
    with SessionLocal() as db:
        db.get(models.User, uid).is_private = private
        db.commit()


def set_banned(uid, banned=True):
    with SessionLocal() as db:
        db.get(models.User, uid).is_banned = banned
        db.commit()


def set_location(headers, lat, lon):
    r = c.post("/me/location", headers=headers,
               json={"lat": lat, "lon": lon, "share": True})
    assert r.status_code == 200 and r.json()["sharing"], r.text


# --- 1. H13: the phone-like pattern --------------------------------------
assert _looks_phone_like("01712345678") is True
assert _looks_phone_like("+880 1712-345678") is True
assert _looks_phone_like("01712 345678") is True
assert _looks_phone_like("(017) 123-4567") is True
assert _looks_phone_like("০১৭১২৩৪৫৬৭৮") is True
assert _looks_phone_like("call me 01712345678 please") is True
assert _looks_phone_like("DM me") is False
assert _looks_phone_like("ward 3") is False
assert _looks_phone_like("bed 12") is False
assert _looks_phone_like("House 12, Road 5") is False
assert _looks_phone_like("Room 12 bed 34") is False
assert _looks_phone_like("needed by 2026-11-25") is False
assert _looks_phone_like("") is False
assert _looks_phone_like(None) is False
print("H13 phone-like pattern (Latin + Bengali, false positives pass) OK")

# --- 2. H12: respond — non-donor may respond; block/private refused -----
# Carol is private; Frank follows her (request + accept).
set_private(1823, True)
r = c.post("/users/1823/follow", headers=FRANK)
assert r.status_code == 200 and r.json().get("requested") is True, r.text
r = c.get("/me/follow-requests", headers=CAROL)
assert r.status_code == 200, r.text
rq = r.json()["follow_requests"][0]["id"]
r = c.post(f"/follow-requests/{rq}/accept", headers=CAROL)
assert r.status_code == 200, r.text

r = c.post("/blood/requests", headers=BOB, json={
    "blood_group": "O+", "hospital": "Dhaka Medical College",
    "city": "Dhaka", "units": 2, "note": "urgent"})
assert r.status_code == 200, r.text
req1 = r.json()["id"]

# Eve is NOT a donor — donor status must not be required to respond.
with SessionLocal() as db:
    assert db.get(models.User, 1825).blood_donor is False
before = blood_responds(1822)
r = c.post(f"/blood/requests/{req1}/respond", headers=EVE)
assert r.status_code == 200, r.text
assert r.json() == {"ok": True, "author_id": 1822}, r.json()
assert blood_responds(1822) == before + 1, "requester must be told"
print("H12 non-donor respond works (200 + notification) OK")

# Author blocked the responder -> 403, no notification.
r = c.post("/users/1824/block", headers=BOB)
assert r.status_code == 200, r.text
before = blood_responds(1822)
r = c.post(f"/blood/requests/{req1}/respond", headers=DAVE)
assert r.status_code == 403, (r.status_code, r.text)
assert blood_responds(1822) == before, "blocked responder must not notify"
r = c.post("/users/1824/block", headers=BOB)
assert r.status_code == 200 and r.json()["blocked"] is False, r.text
print("H12 author-blocked responder -> 403, no notification OK")

# Responder blocked the author -> 403, no notification.
r = c.post("/users/1822/block", headers=DAVE)
assert r.status_code == 200, r.text
before = blood_responds(1822)
r = c.post(f"/blood/requests/{req1}/respond", headers=DAVE)
assert r.status_code == 403, (r.status_code, r.text)
assert blood_responds(1822) == before, "blocker must not notify either"
r = c.post("/users/1822/block", headers=DAVE)
assert r.status_code == 200 and r.json()["blocked"] is False, r.text
print("H12 responder-blocked author -> 403, no notification OK")

# Private author: non-follower refused, follower allowed.
r = c.post("/blood/requests", headers=CAROL, json={
    "blood_group": "O+", "hospital": "Square Hospital",
    "city": "Dhaka", "units": 1})
assert r.status_code == 200, r.text
req2 = r.json()["id"]
before = blood_responds(1823)
r = c.post(f"/blood/requests/{req2}/respond", headers=DAVE)
assert r.status_code == 403, (r.status_code, r.text)
assert blood_responds(1823) == before, "private non-follower must not notify"
r = c.post(f"/blood/requests/{req2}/respond", headers=FRANK)
assert r.status_code == 200, r.text
assert blood_responds(1823) == before + 1
print("H12 private author: non-follower 403, follower 200 OK")

# --- 3. H13: create rejects phone-like contact; read masks stored ones --
for bad_contact in ("01712345678", "+880 1712-345678",
                    "০১৭১২৩৪৫৬৭৮", "call 01712 345678"):
    r = c.post("/blood/requests", headers=BOB, json={
        "blood_group": "O+", "hospital": "H", "city": "Dhaka",
        "units": 1, "contact": bad_contact})
    assert r.status_code == 400, (bad_contact, r.status_code, r.text)
    assert "phone numbers aren't allowed" in r.json()["detail"], r.text
    assert "contact happens by DM" in r.json()["detail"], r.text
for ok_contact in ("DM me", "ward 3", "bed 12"):
    r = c.post("/blood/requests", headers=BOB, json={
        "blood_group": "O+", "hospital": "H", "city": "Dhaka",
        "units": 1, "contact": ok_contact})
    assert r.status_code == 200, (ok_contact, r.status_code, r.text)
    assert r.json()["contact"] == ok_contact, r.json()
# A phone-like contact stored BEFORE the fix never renders.
with SessionLocal() as db:
    db.add(models.BloodRequest(
        author_id=1822, blood_group="O+", hospital="Legacy Hospital",
        city="Dhaka", units=1, note="", contact="01987654321",
        status="open"))
    db.commit()
r = c.get("/blood/requests", headers=ALICE)
assert r.status_code == 200, r.text
legacy = [x for x in r.json()["requests"]
          if x["hospital"] == "Legacy Hospital"]
assert len(legacy) == 1, r.json()
assert legacy[0]["contact"] == "", legacy[0]
assert not any(x["contact"] == "01987654321"
               for x in r.json()["requests"]), r.json()
assert 'placeholder="Ward / timing note (optional)"' in HTML, HTML
assert "Contact info (optional — shown on the request)" not in HTML
print("H13 create rejects phone-like, accepts plain notes, read masks "
      "legacy numbers OK")

# --- 4. Setup for M20/L15/L16: skills, donors, points, locations --------
r = c.post("/me/skills", headers=DAVE,
           json={"skill": "Guitar", "kind": "teach", "note": ""})
assert r.status_code == 200, r.text
r = c.post("/me/skills", headers=EVE,
           json={"skill": "Python", "kind": "teach", "note": ""})
assert r.status_code == 200, r.text
for h, g in ((DAVE, "O+"), (EVE, "O+")):
    r = c.post("/me/blood-group", headers=h,
               json={"blood_group": g, "is_donor": True})
    assert r.status_code == 200, r.text
with SessionLocal() as db:
    db.add(models.PointsLedger(user_id=1824, amount=9999, reason="post"))
    db.add(models.PointsLedger(user_id=1826, amount=100, reason="post"))
    db.commit()
set_location(ALICE, 23.8000, 90.4000)
set_location(DAVE, 23.8009, 90.4000)
set_location(CAROL, 23.8005, 90.4005)
set_location(FRANK, 23.8002, 90.4002)


def search_user_ids(headers, q):
    r = c.get(f"/search?q={q}", headers=headers)
    assert r.status_code == 200, r.text
    return {u["telegram_id"] for u in r.json()["users"]}


def suggested_ids(headers):
    r = c.get("/suggested-users", headers=headers)
    assert r.status_code == 200, r.text
    return {u["telegram_id"] for u in r.json()["users"]}


def skill_ids(headers):
    r = c.get("/skills/directory", headers=headers)
    assert r.status_code == 200, r.text
    return {m["telegram_id"] for m in r.json()["members"]}


def donor_ids(headers):
    r = c.get("/blood/donors", headers=headers)
    assert r.status_code == 200, r.text
    return {d["telegram_id"] for d in r.json()["donors"]}


def nearby_ids(headers):
    r = c.get("/me/nearby", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["sharing"] is True, r.json()
    return {p["id"] for p in r.json()["people"]}


def leader_ids(headers):
    r = c.get("/leaderboard", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# Baselines BEFORE the mute: Dave is visible everywhere.
assert 1824 in search_user_ids(ALICE, "Dave")
assert 1824 in suggested_ids(ALICE)
assert 1824 in skill_ids(ALICE) and 1825 in skill_ids(ALICE)
assert 1824 in donor_ids(ALICE) and 1825 in donor_ids(ALICE)
assert 1824 in nearby_ids(ALICE)
board = leader_ids(ALICE)
assert board["leaders"][0]["telegram_id"] == 1824, board["leaders"][0]
# Above Alice (0 pts): Dave 9999, Frank 100, and the Official
# account (id 1, seeded +10 lifetime) — rank 4.
assert board["me"]["rank"] == 4, board["me"]
# L16 baseline: private Carol is hidden from Alice (non-follower)
# even before any mute, but visible to Frank (follower).
assert 1823 not in nearby_ids(ALICE)
assert 1823 in nearby_ids(FRANK)
print("L15/L16 baselines (Dave visible, private Carol map-hidden "
      "from non-follower) OK")

# --- 5. L15: Alice mutes Dave — he vanishes from every surface ---------
r = c.post("/users/1824/mute", headers=ALICE)
assert r.status_code == 200 and r.json()["muted"] is True, r.text
assert 1824 not in search_user_ids(ALICE, "Dave")
assert 1824 not in suggested_ids(ALICE)
assert 1824 not in skill_ids(ALICE) and 1825 in skill_ids(ALICE)
assert 1824 not in donor_ids(ALICE) and 1825 in donor_ids(ALICE)
assert 1824 not in nearby_ids(ALICE)
board = leader_ids(ALICE)
assert all(x["telegram_id"] != 1824 for x in board["leaders"]), board
# Dave (9999) excluded; Frank (100) and Official (10) still above.
assert board["me"]["rank"] == 3, board["me"]
# Blood requests: Dave's own open request is hidden from Alice.
r = c.post("/blood/requests", headers=DAVE, json={
    "blood_group": "O+", "hospital": "Dave Hospital",
    "city": "Dhaka", "units": 1})
assert r.status_code == 200, r.text
req3 = r.json()["id"]
r = c.get("/blood/requests", headers=ALICE)
assert r.status_code == 200, r.text
got = {x["id"] for x in r.json()["requests"]}
assert req3 not in got, got
assert req1 in got, got
print("L15 muted Dave hidden from search/suggested/skills/blood/"
      "requests/nearby/leaderboard OK")

# Notifications: Dave follows Alice -> the row exists in the DB but
# Alice's list and unread count must not show it.
r = c.post("/users/1821/follow", headers=DAVE)
assert r.status_code == 200, r.text
rows = notif_rows(1821, "follow")
assert any(a == 1824 for _t, a, _r in rows), rows
r = c.get("/me/notifications", headers=ALICE)
assert r.status_code == 200, r.text
listed = r.json()["notifications"]
assert all(n["actor_id"] != 1824 for n in listed), listed
with SessionLocal() as db:
    unread_non_muted = db.query(models.Notification).filter(
        models.Notification.user_id == 1821,
        models.Notification.is_read == False,
        models.Notification.actor_id != 1824).count()
assert r.json()["unread_count"] == unread_non_muted, r.json()
print("L15 muted actor hidden from notifications list + unread OK")

# DMs are untouched: a DM from the muted author still delivers.
r = c.post("/messages/1821", json={"text": "hi Alice, muted DM"},
           headers=DAVE)
assert r.status_code == 200, (r.status_code, r.text)
r = c.get("/messages/1824", headers=ALICE)
assert r.status_code == 200, r.text
assert any(m.get("text") == "hi Alice, muted DM"
           for m in r.json().get("messages", [])), r.json()
print("L15 DMs untouched (muted author DM delivers + reads) OK")

# --- 6. M20: unmute proves mute was the cause; ban hides him again ------
r = c.post("/users/1824/mute", headers=ALICE)
assert r.status_code == 200 and r.json()["muted"] is False, r.text
assert 1824 in search_user_ids(ALICE, "Dave")
set_banned(1824, True)
assert 1824 not in search_user_ids(ALICE, "Dave")
assert 1824 not in skill_ids(ALICE) and 1825 in skill_ids(ALICE)
assert 1824 not in donor_ids(ALICE) and 1825 in donor_ids(ALICE)
# Skill Connect to a banned member -> 403, no notification.
before = len(notif_rows(1824, "skill_connect"))
r = c.post("/skills/1824/connect", headers=ALICE)
assert r.status_code == 403, (r.status_code, r.text)
assert len(notif_rows(1824, "skill_connect")) == before
# Connect to a clean member still works.
before = len(notif_rows(1825, "skill_connect"))
r = c.post("/skills/1825/connect", headers=ALICE)
assert r.status_code == 200, r.text
assert len(notif_rows(1825, "skill_connect")) == before + 1
print("M20 banned hidden from skill/blood/search; Skill Connect "
      "403 to banned, 200 to clean OK")

# --- 7. L20: fuzz offset stable per member, still 50-100 m ---------------
def hav_m(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2
         + math.cos(lat1 * p) * math.cos(lat2 * p)
         * (1 - math.cos((lon2 - lon1) * p)) / 2)
    return 12742000 * math.asin(math.sqrt(a))


lat, lon = 23.8000, 90.4000
a1 = _fuzz(lat, lon, 1821)
a2 = _fuzz(lat, lon, 1821)
assert a1 == a2, "fuzz must be identical across calls/days"
d = hav_m(lat, lon, a1[0], a1[1])
assert 50 <= d <= 100, d
b1 = _fuzz(lat, lon, 1822)
assert b1 != a1, "different members get different offsets"
assert 50 <= hav_m(lat, lon, b1[0], b1[1]) <= 100
# The seed no longer carries a date: no %Y-%m-%d in the _fuzz body.
seg = MAIN[MAIN.index("def _fuzz("):MAIN.index("def _fuzz(") + 1200]
assert "%Y-%m-%d" not in seg, seg
assert "nx-fuzz:{tid}" in seg, seg
print("L20 fuzz member-stable, 50-100 m, no date in seed OK")

# --- 8. L17/L18/M21: JS — foot routing, abort, Street View budget --------
assert '"foot/" + nbPos.lon' in JS, "routing must use the foot profile"
assert '"driving/" + nbPos.lon' not in JS, "driving profile must be gone"
assert "AbortController" in JS, JS
sv = JS[JS.index("function nbFetchTimeout"):]
assert "new AbortController()" in sv, sv
assert "signal: ctl.signal" in sv, sv
assert "ctl.abort()" in sv, sv
assert "NB_SV_LOOKUP_BUDGET_MS = 9000" in JS
assert "NB_SV_ATTEMPT_MS = 5000" in JS
# The budget constants must live INSIDE nbSVLookup: the Phase 149
# node harness extracts that function alone, so module-scope
# consts would be undefined there (this broke test_phase149 once).
assert JS.index("NB_SV_LOOKUP_BUDGET_MS = 9000") > \
    JS.index("async function nbSVLookup"), JS
assert "r.ok === false" in JS
assert "r.status === 401 || r.status === 403" in JS
assert "Couldn't load Street View — access was refused" in JS
assert "Couldn't load Street View right now" in JS
assert "No street-level photo here yet." in JS
lookup = JS[JS.index("async function nbSVLookup"):]
lookup = lookup[:lookup.index("\n}\n") + 3]
assert ", 8000)" not in lookup, "no second 8 s attempt may remain"
assert "new Promise(res => setTimeout(() => res(false), 10000))" in JS, \
    "the 10 s viewer race must stay"
print("L17/L18/M21 JS (foot profile, AbortController, 9 s budget, "
      "honest auth line, 10 s viewer race) OK")

# --- 9. Version, markers, routes, backup tables --------------------------
assert HTML.count("?v=190") == 10, HTML.count("?v=190")
assert "?v=18" + "1" not in HTML
r = c.get("/admin/health", headers=ADMIN)
assert r.status_code == 200, r.text
assert r.json()["version"] == 190, r.json()
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
for m in ("_looks_phone_like",
          "phone numbers aren't allowed — contact happens by DM",
          "This member is not available",
          "NB_SV_LOOKUP_BUDGET_MS",
          "NB_SV_ATTEMPT_MS"):
    assert m in MAIN or m in JS, m
print("version ?v=190 x10 + health 182 + routes/backup markers OK")

print("PHASE 182 OK")
