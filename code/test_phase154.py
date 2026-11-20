"""Phase-154 tests: donor cards show the member's real profile photo
(owner order Nov 20, 2026, 07:06 Dhaka: "donor's profile photo
cannot be seen — why?").

Root cause: _blood_donor_out() never returned photo_file_id, and
the donor card passed null to avatarEl(), so it always fell through
to the initials div. Fix: the server row carries photo_file_id and
the card passes it to avatarEl (onerror/initials fallback intact
when it is null). Request cards are text-only by design — no avatar
there, left alone. The photo sync path (POST /me/photo/sync, called
on app open when no photo is stored) already populates
photo_file_id; no new sync mechanism. No new endpoints, no schema
change.
"""
import hashlib, hmac, json, os, re, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase154.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app, SessionLocal
from app import models


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData",
                      os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


ALICE = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()
MAIN = open("app/main.py").read()

# 1. Server row carries the photo; client passes it to avatarEl.
seg = MAIN[MAIN.index("def _blood_donor_out"):]
seg = seg[:seg.index("def _blood_visible_donors")]
assert '"photo_file_id": u.photo_file_id' in seg, seg
assert "Phase 154" in seg
don = JS[JS.index("async function loadBloodDonors()"):]
don = don[:don.index("async function loadBloodRequests()")]
assert "avatarEl(u.first_name, u.telegram_id, false, u.photo_file_id)" in don
assert "avatarEl(u.first_name, u.telegram_id, false, null)" not in don
assert "Phase 154: the real profile photo" in don
# avatarEl itself still falls back to initials when photoId is null.
av = JS[JS.index("function avatarEl"):]
av = av[:av.index("function ", 10)]
assert "if (photoId) {" in av
assert 'img.onerror = () => img.replaceWith(avatarEl(name, id, big));' in av
print("photo plumbing OK (row carries photo_file_id, card passes it, fallback intact)")

# 2. Request cards stay text-only by design: no avatar in
# loadBloodRequests, and _blood_request_out gains no photo field.
req = JS[JS.index("async function loadBloodRequests()"):]
nxt = req.find("\nasync function ", 10)
req = req[:nxt] if nxt != -1 else req
assert "avatarEl" not in req
rseg = MAIN[MAIN.index("def _blood_request_out"):]
rseg = rseg[:rseg.index("class BloodGroupIn")]
assert "photo" not in rseg
print("request cards untouched OK (text-only by design)")

# 3. The photo sync path already exists: POST /me/photo/sync pulls
# the Telegram profile picture when none is stored, and the client
# calls it on app open when me.photo_file_id is empty.
assert "fetch_telegram_photo_file_id" in MAIN
assert 'api("/me/photo/sync", { method: "POST" })' in JS
assert "if (!me.photo_file_id) {" in JS
print("photo sync path intact OK (sync on app open, no new mechanism)")

with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 4. Donor WITH a stored photo gets it in the row; donor WITHOUT
    # one gets null — and the key set is exact (no phone/location).
    db = SessionLocal()
    carol = db.get(models.User, 333)
    carol.photo_file_id = "FAKEPHOTO_CAROL"
    db.commit()
    db.close()
    assert c.post("/me/blood-group", headers=CAROL,
                  json={"blood_group": "A-", "is_donor": True}).status_code == 200
    assert c.post("/me/blood-group", headers=ALICE,
                  json={"blood_group": "O-", "is_donor": True}).status_code == 200
    r = c.get("/blood/donors", headers=BOB)
    assert r.status_code == 200, r.text
    by_id = {d["telegram_id"]: d for d in r.json()["donors"]}
    assert set(by_id) == {111, 333}, by_id
    assert by_id[333]["photo_file_id"] == "FAKEPHOTO_CAROL", by_id[333]
    assert by_id[111]["photo_file_id"] is None, by_id[111]
    for d in by_id.values():
        assert set(d.keys()) == {"telegram_id", "first_name",
                                 "username", "blood_group",
                                 "country", "photo_file_id"}, d.keys()
        assert "phone" not in json.dumps(d).lower()
    print("donors rows OK (photo passes through, null stays null, exact keys)")

    # 5. No new endpoints, no schema change: routes still 158,
    # backup still 43 tables.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 43, len(r.json()["tables"])
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 158, len(paths)
    assert len([p for p in paths if "blood" in p]) == 6, paths
    print("routes 158 + backup 43 tables OK (no new endpoints, no schema change)")

# 6. Neighbours intact.
assert "loadBloodDonors" in JS and "loadBloodRequests" in JS
assert "settings-blood-save" in JS
assert "bloodDistance" in JS and JS.count("function bloodDistance") == 1
assert "bloodMaybeAskLocation" in JS and "blood-loc-hint" in HTML
assert "openNearby" in JS and "nbLocate" in JS
assert "avatarEl(p.author_name, p.author_id, false, p.author_photo)" in JS, \
    "feed author photos must keep passing author_photo"
assert "museum" not in JS.lower() and "museum" not in HTML.lower()
print("neighbours OK (Blood flows, distance, Nearby, feed photos, no museum)")

# 7. Version.
assert HTML.count("?v=155") == 10, HTML.count("?v=155")
assert "?v=15" + "3" not in HTML
assert 'menu_url.rstrip("/") + "/?v=155"' in BOT
print("PHASE 154 OK")
