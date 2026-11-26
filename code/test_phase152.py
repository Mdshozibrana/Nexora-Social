"""Phase-152 tests: donor card one-line name, no username, donor
distance, and the Museum removal (owner orders Nov 20, 2026,
05:38 Dhaka, from his Blood-page screenshot + follow-up).

Donor card: first_name only (no @username), full name on ONE
line ("MD Shozib Rana" fits whole at 360px), the group badge
never overlaps the text, Message still opens the DM. Second
line is country + distance when both sides share location
("Bangladesh · 3.2 km away" / "350 m away"), country only
otherwise. Server computes distance_km (haversine, same math
as Nearby) only when viewer AND donor share location, and never
returns any donor lat/lon. Museum: gone entirely (see the
converted test_phase86/87 removal guards).
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

import math


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


def hav(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 6371000 * 2 * math.asin(math.sqrt(a))


def fmt_dist(d):
    """Mirror of the client's bloodDistance(): metres under 1 km,
    one-decimal km otherwise."""
    if d < 1:
        return f"{round(d * 1000)} m away"
    return f"{d:.1f} km away"


ALICE = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()
MAIN = open("app/main.py").read()

PA = {"lat": 23.81030, "lon": 90.41250}   # viewer
PB = {"lat": 23.81210, "lon": 90.41250}   # ~200 m north of PA
PC = {"lat": 23.82830, "lon": 90.41250}   # ~2.0 km north of PA

# 1. Donor card: first_name only, two rows, distance helper.
seg = JS[JS.index("async function loadBloodDonors()"):]
seg = seg[:seg.index("async function loadBloodRequests()")]
assert "u.username" not in seg, "username still built in donor cards"
# Phase 163: the name moved into the shared .vname line —
# still first_name only, now in a .vname-text span + tick.
assert 'nmText.textContent = u.first_name;' in seg
assert 'className = "blood-top"' in seg
assert 'className = "blood-bottom"' in seg
assert "bloodDistance(u.distance_km)" in seg
assert '" · "' in seg  # country + distance joined with ·
assert "function bloodDistance(d) {" in JS
assert '" m away"' in JS and '" km away"' in JS
assert "toFixed(1)" in JS
assert "Math.round(d * 1000)" in JS
# One-line name rules + two-row layout in CSS.
name_blocks = re.findall(r"\.blood-name\s*\{[^}]*\}", CSS)
assert name_blocks, "no .blood-name rule"
assert any("white-space: nowrap" in b and "text-overflow: ellipsis" in b
           for b in name_blocks), name_blocks
assert ".blood-donor-card { flex-direction: column;" in CSS
assert ".blood-top { display: flex; align-items: center; gap: 10px; }" in CSS
assert ".blood-bottom { display: flex; align-items: center; gap: 10px; }" in CSS
assert "Phase 152: donor card" in CSS
# Request cards share .blood-name and still build hospital · city.
assert 'r.hospital + " · " + r.city' in JS
assert "bloodGroupBadge" in JS
print("donor card code OK (first_name only, two rows, bloodDistance)")

# 2. Layout simulation at 360px and 420px (Phase 150 style).
# Card inner width = viewport - 24 (#app-scroll) - 20 (card padding).
# Row 1: avatar 42 + gap 10 + name (15px bold, ~8.0px/char) + gap 10
# + badge (emoji ~17 + " A+" ~22 + padding 20 = ~59).
# Row 2: country + distance (muted ~16px, ~8.0px/char) + gap 10
# + Message (emoji ~17 + " Message" ~58 + padding 24 = ~99).
NAME_W = len("MD Shozib Rana") * 8.0
BADGE_W = 17.0 + 3 * 7.3 + 20.0
ROW1 = 42.0 + 10.0 + NAME_W + 10.0 + BADGE_W
LINE2 = len("Bangladesh · 3.2 km away") * 8.0
MSG_W = 17.0 + 8 * 7.3 + 24.0
ROW2 = LINE2 + 10.0 + MSG_W
for viewport, inner in ((360, 316.0), (420, 376.0)):
    assert ROW1 <= inner, (viewport, ROW1)
    assert ROW2 <= inner, (viewport, ROW2)
    print(f"donor card {viewport}px OK: row1={ROW1:.0f} row2={ROW2:.0f} "
          f"<= {inner:.0f}px inner (name + distance line fit whole)")
# A very long name (30 chars) exceeds the name slot, so the
# ellipsis safety net — not an overlap — is what keeps it one line.
avail = 316.0 - 42.0 - 10.0 - BADGE_W - 10.0
assert 30 * 8.0 > avail, avail
assert "text-overflow: ellipsis" in CSS
print("long-name ellipsis safety net OK")

# 3. Distance formatting mirror.
assert fmt_dist(0.2) == "200 m away", fmt_dist(0.2)
assert fmt_dist(0.35) == "350 m away", fmt_dist(0.35)
assert fmt_dist(3.24) == "3.2 km away", fmt_dist(3.24)
assert fmt_dist(2.0) == "2.0 km away", fmt_dist(2.0)
print("distance formatting OK (m under 1 km, 1-decimal km above)")

# 4. Server: distance_km only when both sides share location.
with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200
    for h, g in ((BOB, "A+"), (CAROL, "O+")):
        r = c.post("/me/blood-group", headers=h,
                   json={"blood_group": g, "is_donor": True})
        assert r.status_code == 200, r.text
    # Locations: viewer PA, near donor PB (~0.2 km), far donor PC (~2 km).
    for h, p in ((ALICE, PA), (BOB, PB), (CAROL, PC)):
        r = c.post("/me/location", headers=h,
                   json={**p, "share": True})
        assert r.status_code == 200, r.text
    r = c.get("/blood/donors", headers=ALICE)
    assert r.status_code == 200, r.text
    by_id = {d["telegram_id"]: d for d in r.json()["donors"]}
    assert 222 in by_id and 333 in by_id, by_id
    for d in by_id.values():
        assert "lat" not in d and "lon" not in d, d
        assert "latitude" not in d and "longitude" not in d, d
    exp_bob = hav(PA["lat"], PA["lon"], PB["lat"], PB["lon"]) / 1000.0
    exp_carol = hav(PA["lat"], PA["lon"], PC["lat"], PC["lon"]) / 1000.0
    assert abs(by_id[222]["distance_km"] - round(exp_bob, 2)) <= 0.05, by_id[222]
    assert abs(by_id[333]["distance_km"] - round(exp_carol, 2)) <= 0.05, by_id[333]
    assert by_id[222]["distance_km"] < 1 and by_id[333]["distance_km"] > 1
    print(f"distance OK: near={by_id[222]['distance_km']} km "
          f"far={by_id[333]['distance_km']} km, no lat/lon leaked")

    # Viewer stops sharing -> no distance_km anywhere, key set
    # identical to the pre-152 response.
    r = c.post("/me/location", headers=ALICE,
               json={"lat": 0, "lon": 0, "share": False})
    assert r.status_code == 200, r.text
    r = c.get("/blood/donors", headers=ALICE)
    for d in r.json()["donors"]:
        assert "distance_km" not in d, d
        assert set(d.keys()) == {"telegram_id", "first_name",
                                 "username", "blood_group", "country",
                                 "photo_file_id", "is_verified"}, d
    print("distance omitted when the viewer does not share: OK")

    # Donor stops sharing -> only that donor loses distance.
    r = c.post("/me/location", headers=ALICE,
               json={**PA, "share": True})
    assert r.status_code == 200, r.text
    r = c.post("/me/location", headers=BOB,
               json={"lat": 0, "lon": 0, "share": False})
    assert r.status_code == 200, r.text
    r = c.get("/blood/donors", headers=ALICE)
    by_id = {d["telegram_id"]: d for d in r.json()["donors"]}
    assert "distance_km" not in by_id[222], by_id[222]
    assert "distance_km" in by_id[333], by_id[333]
    print("distance omitted when the donor does not share: OK")

# 5. Museum removal (same assertions as the converted guards).
assert "museum" not in HTML.lower()
assert "museum" not in JS.lower()
assert "museum" not in CSS.lower()
assert 'data-go="museum"' not in HTML
assert '<section id="view-museum"' not in HTML
assert '"nearby", "qr", "trending", "settings", "blood", "skills"]' in JS
assert "openMuseum" not in JS and "loadMuseum" not in JS
assert "MUSEUM_THEMES" not in JS and "museumZoom" not in JS
# Neighbours intact: Blood page, Settings opt-in, Design, Nearby, DMs.
assert 'data-go="blood"' in HTML and 'id="view-blood"' in HTML
assert "settings-blood-save" in JS
assert "loadDesigns" in JS and "design-grid" in HTML
assert "openNearby" in JS and "loadMessages" in JS
assert "distance_km" in MAIN and "me_shares" in MAIN
print("Museum removal + neighbours OK")

# 6. Version.
assert HTML.count("?v=191") == 10, HTML.count("?v=191")
assert "?v=15" + "1" not in HTML
assert 'menu_url.rstrip("/") + "/?v=191"' in BOT
print("PHASE 152 OK")
