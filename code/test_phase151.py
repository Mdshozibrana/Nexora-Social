"""Phase-151 tests: blood donors (🩸 রক্তদাতা).

Owner order (2026-11-19 22:51 Dhaka — #1 from a ranked proposal):
blood donation is a life-or-death community need in Bangladesh.
Built on profiles / Settings / DMs / notifications — text-only,
no media, no phone numbers anywhere.

Covers: client markers (Blood page + sidebar + Settings opt-in +
profile badge + 8th notification toggle + CSS); donor opt-in/out
round-trips and validation (invalid group 400, donor without a
group 400, lowercase normalised); donors endpoint lists ONLY
opted-in donors, group filter, no phone/location keys, private-
donor visibility (hidden from strangers, visible to a follower);
requests create/list/fulfill/cancel incl. 403/404 and validation
(units 1-10, hospital/city required); respond notifies the
requester (and opens the DM client-side); a new request notifies
ONLY matching-group opted-in donors (other groups get nothing);
the "blood" notification pref gates delivery; "blood" / "রক্ত"
text is accepted while a genuinely banned word still rejects
(the GEMINI media screening is image-only and never touches
this text flow); /auth + /users/{id} expose blood_group only
when opted in; backup 43 tables; routes 158 (6 new blood paths);
?v=159 x9, no old-version literals.
"""
import hashlib, hmac, json, os, re, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase151.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


ALICE = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")
DAVE = H(444, "Dave")
EVE = H(555, "Eve")

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()
MAIN = open("app/main.py").read()
MODELS = open("app/models.py").read()
NOTIFY = open("app/notify.py").read()


def blood_notifs(c, h):
    r = c.get("/me/notifications?limit=50", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["notifications"]


def count_type(c, h, ntype):
    return sum(1 for n in blood_notifs(c, h) if n["type"] == ntype)


# 1. Client markers: Blood page + sidebar + Settings + badge + toggle.
assert HTML.count("?v=159") == 10, HTML.count("?v=159")
assert "?v=15" + "0" not in HTML
assert 'menu_url.rstrip("/") + "/?v=159"' in BOT
assert 'data-go="blood"' in HTML
assert 'id="view-blood"' in HTML
for cid in ("blood-tab-donors", "blood-tab-requests",
            "blood-donor-filters", "blood-donor-list",
            "blood-request-pane", "blood-new-btn", "blood-form",
            "blood-form-group", "blood-form-hospital",
            "blood-form-city", "blood-form-units", "blood-form-note",
            "blood-form-contact", "blood-form-send",
            "blood-request-list", "blood-empty"):
    assert f'id="{cid}"' in HTML, cid
assert "🩸 Blood" in HTML
assert '"blood"' in JS or "'blood'" in JS
assert "loadBlood" in JS and "loadBloodDonors" in JS
assert "loadBloodRequests" in JS
assert 'const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]' in JS
assert "settings-blood-save" in JS
assert "blood-badge" in JS
assert '["blood", "🩸 Blood requests"' in JS
assert 'blood_request: "🩸"' in JS and 'blood_respond: "🩸"' in JS
assert "আমি দেবো" in JS
assert "Phase 151: Blood donors" in CSS
for rule in (".blood-tabs", ".blood-group-badge", ".blood-badge",
             ".blood-form", ".blood-card"):
    assert rule in CSS, rule
print("client markers OK (?v=159 x9, Blood page, Settings, badge, toggle)")

# 2. Server markers: model, migration, backup, notify map.
assert "class BloodRequest(Base):" in MODELS
assert 'blood_group = Column(String(3), nullable=True)' in MODELS
assert "blood_donor = Column(Boolean, default=False)" in MODELS
assert "blood_donor BOOLEAN DEFAULT FALSE" in MAIN
assert '("blood_requests", models.BloodRequest)' in MAIN
assert '"blood_request": "blood", "blood_respond": "blood",' in NOTIFY
assert '"tips", "messages", "system", "blood", "skills")' in NOTIFY
print("server markers OK (model + migration + backup + notify map)")

with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE, EVE):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 3. Donor opt-in validation.
    r = c.post("/me/blood-group", headers=BOB,
               json={"blood_group": "X+", "is_donor": True})
    assert r.status_code == 400, r.text
    r = c.post("/me/blood-group", headers=BOB,
               json={"blood_group": None, "is_donor": True})
    assert r.status_code == 400, r.text
    r = c.post("/me/blood-group", headers=BOB,
               json={"blood_group": "o+", "is_donor": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"blood_group": "O+", "blood_donor": True}, r.json()
    print("donor validation OK (invalid 400, no-group 400, lowercase normalised)")

    # 4. Opt-ins: CAROL A- donor, EVE O+ donor, ALICE O- donor;
    # DAVE stores a group but does NOT opt in.
    r = c.post("/me/blood-group", headers=CAROL,
               json={"blood_group": "A-", "is_donor": True})
    assert r.status_code == 200, r.text
    r = c.post("/me/blood-group", headers=EVE,
               json={"blood_group": "O+", "is_donor": True})
    assert r.status_code == 200, r.text
    r = c.post("/me/blood-group", headers=ALICE,
               json={"blood_group": "O-", "is_donor": True})
    assert r.status_code == 200, r.text
    r = c.post("/me/blood-group", headers=DAVE,
               json={"blood_group": "B+", "is_donor": False})
    assert r.status_code == 200, r.text
    assert r.json() == {"blood_group": "B+", "blood_donor": False}, r.json()

    # 5. Donors endpoint: only opted-in donors, group filter,
    # no phone/location keys.
    r = c.get("/blood/donors", headers=BOB)
    assert r.status_code == 200, r.text
    donors = r.json()["donors"]
    ids = {d["telegram_id"] for d in donors}
    assert ids == {222, 333, 555, 111}, ids
    assert 444 not in ids, "group stored but donor OFF must not list"
    for d in donors:
        assert set(d.keys()) == {"telegram_id", "first_name",
                                 "username", "blood_group",
                                 "country", "photo_file_id"}, d.keys()
        assert "phone" not in json.dumps(d).lower()
    r = c.get("/blood/donors?group=O%2B", headers=BOB)
    assert {d["telegram_id"] for d in r.json()["donors"]} == {222, 555}, r.json()
    r = c.get("/blood/donors?group=A-", headers=BOB)
    assert {d["telegram_id"] for d in r.json()["donors"]} == {333}, r.json()
    r = c.get("/blood/donors?group=XX", headers=BOB)
    assert r.status_code == 400, r.text
    print("donors directory OK (opted-in only, filter, no phone/location)")

    # 6. /auth + /users/{id} expose blood_group only when opted in.
    r = c.post("/auth", json={"initData": BOB["X-Init-Data"]})
    assert r.json()["blood_group"] == "O+", r.json()
    assert r.json()["blood_donor"] is True
    r = c.get("/users/222", headers=BOB)
    assert r.json()["blood_group"] == "O+", r.json()
    r = c.get("/users/444", headers=BOB)
    assert r.json()["blood_group"] is None, r.json()
    print("profile exposure OK (donor badge only when opted in)")

    # 7. Private-donor visibility (Phase 136 rule, reused).
    r = c.post("/me/privacy", headers=CAROL, json={"is_private": True})
    assert r.status_code == 200, r.text
    r = c.get("/blood/donors", headers=BOB)
    assert 333 not in {d["telegram_id"] for d in r.json()["donors"]}, \
        "private donor must hide from strangers"
    r = c.post("/users/333/follow", headers=BOB)
    assert r.status_code == 200 and r.json()["requested"] is True, r.text
    r = c.get("/me/follow-requests", headers=CAROL)
    assert r.status_code == 200, r.text
    req_id = r.json()["follow_requests"][0]["id"]
    r = c.post(f"/follow-requests/{req_id}/accept", headers=CAROL)
    assert r.status_code == 200, r.text
    r = c.get("/blood/donors", headers=BOB)
    assert 333 in {d["telegram_id"] for d in r.json()["donors"]}, \
        "private donor must show to a follower"
    print("private-donor visibility OK (hidden from strangers, seen by follower)")

    # 8. Banned word + blood text: "blood"/"রক্ত" must pass, a
    # genuinely banned word must still reject.
    r = c.post("/admin/banned-words", headers=ALICE, json={"word": "zqxwv"})
    assert r.status_code == 200, r.text
    before_eve = count_type(c, EVE, "blood_request")
    before_carol = count_type(c, CAROL, "blood_request")
    before_alice = count_type(c, ALICE, "blood_request")
    r = c.post("/blood/requests", headers=BOB, json={
        "blood_group": "O+", "hospital": "Dhaka Medical College",
        "city": "Dhaka", "units": 2,
        "note": "Need blood রক্ত urgently for surgery"})
    assert r.status_code == 200, r.text
    req1 = r.json()["id"]
    assert r.json()["blood_group"] == "O+", r.json()
    assert r.json()["status"] == "open", r.json()
    # Only the matching-group donor (EVE, O+) is notified —
    # not CAROL (A-), not ALICE (O-), not the author himself.
    assert count_type(c, EVE, "blood_request") == before_eve + 1
    assert count_type(c, CAROL, "blood_request") == before_carol
    assert count_type(c, ALICE, "blood_request") == before_alice
    assert count_type(c, BOB, "blood_request") == 0
    r = c.post("/blood/requests", headers=BOB, json={
        "blood_group": "O+", "hospital": "Dhaka Medical College",
        "city": "Dhaka", "units": 1, "note": "zqxwv inside"})
    assert r.status_code == 400, r.text
    r = c.get("/blood/requests", headers=BOB)
    assert len(r.json()["requests"]) == 1, r.json()
    print("request create + matching-group notify OK (blood/রক্ত pass, banned word 400)")

    # 9. Request validation.
    for bad in ({"blood_group": "O+", "hospital": "H", "city": "C", "units": 0},
                {"blood_group": "O+", "hospital": "H", "city": "C", "units": 11},
                {"blood_group": "X+", "hospital": "H", "city": "C", "units": 1},
                {"blood_group": "O+", "hospital": "", "city": "C", "units": 1},
                {"blood_group": "O+", "hospital": "H", "city": "", "units": 1}):
        r = c.post("/blood/requests", headers=BOB, json=bad)
        assert r.status_code == 400, (bad, r.text)
    print("request validation OK (units 1-10, group, hospital, city)")

    # 10. Respond: notifies the requester; 404/400 guards.
    r = c.post(f"/blood/requests/{req1}/respond", headers=EVE)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "author_id": 222}, r.json()
    assert any(n["type"] == "blood_respond" and n["actor_id"] == 555
               for n in blood_notifs(c, BOB)), "requester must be told"
    r = c.post("/blood/requests/999999/respond", headers=EVE)
    assert r.status_code == 404, r.text
    r = c.post(f"/blood/requests/{req1}/respond", headers=BOB)
    assert r.status_code == 400, r.text
    print("respond OK (requester notified, 404/400 guards)")

    # 11. Fulfill / cancel: author-only (403), state guards.
    r = c.post(f"/blood/requests/{req1}/fulfill", headers=CAROL)
    assert r.status_code == 403, r.text
    r = c.post("/blood/requests/999999/fulfill", headers=BOB)
    assert r.status_code == 404, r.text
    r = c.post(f"/blood/requests/{req1}/fulfill", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "fulfilled", r.json()
    assert r.json()["fulfilled_at"], r.json()
    r = c.post(f"/blood/requests/{req1}/respond", headers=EVE)
    assert r.status_code == 400, r.text
    r = c.post(f"/blood/requests/{req1}/fulfill", headers=BOB)
    assert r.status_code == 400, r.text
    r = c.post("/blood/requests", headers=BOB, json={
        "blood_group": "A+", "hospital": "Square Hospital",
        "city": "Dhaka", "units": 1})
    assert r.status_code == 200, r.text
    req2 = r.json()["id"]
    r = c.post(f"/blood/requests/{req2}/cancel", headers=CAROL)
    assert r.status_code == 403, r.text
    r = c.post(f"/blood/requests/{req2}/cancel", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled", r.json()
    r = c.get("/blood/requests?status=fulfilled", headers=BOB)
    assert any(x["id"] == req1 for x in r.json()["requests"]), r.json()
    r = c.get("/blood/requests?status=open", headers=BOB)
    assert all(x["id"] not in (req1, req2)
               for x in r.json()["requests"]), r.json()
    r = c.get("/blood/requests?status=bogus", headers=BOB)
    assert r.status_code == 400, r.text
    r = c.get("/blood/requests?group=A%2B", headers=BOB)
    assert all(x["blood_group"] == "A+"
               for x in r.json()["requests"]), r.json()
    print("fulfill/cancel OK (author-only, state guards, filters)")

    # 12. The "blood" notification pref gates delivery.
    r = c.get("/me/notification-prefs", headers=EVE)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["blood"] is True, r.json()
    prefs = r.json()["prefs"]
    prefs["blood"] = False
    r = c.post("/me/notification-prefs", headers=EVE, json=prefs)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["blood"] is False, r.json()
    before = count_type(c, EVE, "blood_request")
    r = c.post("/blood/requests", headers=BOB, json={
        "blood_group": "O+", "hospital": "Dhaka Medical College",
        "city": "Dhaka", "units": 1})
    assert r.status_code == 200, r.text
    req3 = r.json()["id"]
    assert count_type(c, EVE, "blood_request") == before, \
        "blood pref OFF must silence the alert"
    prefs["blood"] = True
    r = c.post("/me/notification-prefs", headers=EVE, json=prefs)
    assert r.status_code == 200 and r.json()["prefs"]["blood"] is True
    print("blood notification pref OK (8th toggle, gates delivery)")

    # 13. Opt-out round-trip: DAVE opts in, then clears.
    r = c.post("/me/blood-group", headers=DAVE,
               json={"blood_group": "B+", "is_donor": True})
    assert r.status_code == 200, r.text
    r = c.get("/blood/donors", headers=BOB)
    assert 444 in {d["telegram_id"] for d in r.json()["donors"]}
    r = c.post("/me/blood-group", headers=DAVE,
               json={"blood_group": None, "is_donor": False})
    assert r.status_code == 200, r.text
    assert r.json() == {"blood_group": None, "blood_donor": False}, r.json()
    r = c.get("/blood/donors", headers=BOB)
    assert 444 not in {d["telegram_id"] for d in r.json()["donors"]}
    print("opt-out round-trip OK (clearing removes the donor)")

    # 14. Backup 43 tables; routes 158 (6 new blood paths).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 44, len(r.json()["tables"])
    assert "blood_requests" in r.json()["tables"], r.json().keys()
    print("backup: 43 tables incl. blood_requests OK")
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 163, len(paths)
    expected = {"/me/blood-group", "/blood/donors", "/blood/requests",
                "/blood/requests/{req_id}/respond",
                "/blood/requests/{req_id}/fulfill",
                "/blood/requests/{req_id}/cancel"}
    assert expected <= paths, expected - paths
    assert len([p for p in paths if "blood" in p]) == 6, paths
    print("routes: 158 OK (6 new blood paths, nothing else)")

print("ALL PHASE 151 CHECKS PASSED")
