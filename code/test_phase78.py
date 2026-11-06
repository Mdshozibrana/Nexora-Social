"""Phase-78 tests: Nearby (owner: a sidebar map showing who
is using the bot within 500 m right now, blue dots, tap for
the name and profile, and a live walking route).

Safety contract under test: seeing others requires sharing
yourself; only fresh (<=10 min) opt-ins appear; blocked pairs
never see each other; strangers are fuzzed 50-100 m; mutual
follows see the exact spot; turning sharing off deletes the
stored location and removes the member everywhere.
"""
import hashlib, hmac, json, math, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase78.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()
MAIN = open("app/main.py").read()

# --- client + wiring contract ------------------------------------
for bit in ('data-go="nearby"', 'id="view-nearby"', 'id="nearby-map"',
            'id="nearby-toggle"', "vendor/leaflet/leaflet.js?v=94",
            "vendor/leaflet/leaflet.css?v=94"):
    assert bit in HTML, bit
for bit in ("function openNearby()", "function stopNearby()",
            '"nearby") openNearby()', "nbLocate", "LocationManager",
            "routing.openstreetmap.de", "data-nb-profile",
            "data-nb-route", "tile.openstreetmap.org",
            '"assistant", "nearby", "museum"]'):
    assert bit in JS, bit
assert "routing.openstreetmap.de" in MAIN  # CSP connect-src
assert "share_location" in open("app/models.py").read()
assert '"location": (300, 3600)' in open("app/config.py").read()
assert "app.js?v=94" in HTML and "style.css?v=94" in HTML
import os.path
assert os.path.getsize("webapp/vendor/leaflet/leaflet.js") > 100000
print("client + wiring contract OK")


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)

def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


def hav(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 6371000 * 2 * math.asin(math.sqrt(a))


A = H(111, "Alice")
B = H(222, "Bob")
C = H(333, "Carol")
D = H(444, "Dave")
E = H(555, "Erin")

# Alice in Dhaka; Bob ~200 m north; Carol ~2 km north;
# Erin ~100 m east (will be blocked); Dave ~150 m north (never shares).
PA = {"lat": 23.81030, "lon": 90.41250}
PB = {"lat": 23.81210, "lon": 90.41250}
PC = {"lat": 23.82830, "lon": 90.41250}
PE = {"lat": 23.81030, "lon": 90.41340}

with TestClient(app) as c:
    for h in (A, B, C, D, E):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # unauthenticated is refused
    assert c.get("/me/nearby").status_code == 401
    assert c.post("/me/location", json={**PA, "share": True}).status_code == 401

    # nobody sharing yet -> the caller is not sharing either
    r = c.get("/me/nearby", headers=A).json()
    assert r == {"sharing": False, "people": []}, r

    # invalid coordinates are rejected
    r = c.post("/me/location", headers=A,
               json={"lat": 999, "lon": 0, "share": True})
    assert r.status_code == 400, r.text

    # everyone but Dave turns sharing on
    for h, p in ((A, PA), (B, PB), (C, PC), (E, PE)):
        r = c.post("/me/location", headers=h, json={**p, "share": True})
        assert r.status_code == 200 and r.json()["sharing"], r.text

    # Alice blocks Erin: Erin must vanish from Alice's map
    r = c.post("/users/555/block", headers=A)
    assert r.status_code == 200, r.text

    r = c.get("/me/nearby", headers=A).json()
    assert r["sharing"] is True, r
    ids = [q["id"] for q in r["people"]]
    assert ids == [222], ids  # Carol too far, Dave not sharing, Erin blocked
    bob = r["people"][0]
    assert 120 <= bob["distance_m"] <= 320, bob
    assert bob["mutual"] is False
    # a stranger is fuzzed: the dot sits 40-130 m from Bob's true spot
    off = hav(bob["lat"], bob["lon"], PB["lat"], PB["lon"])
    assert 40 <= off <= 130, off

    # mutual follows -> exact position
    assert c.post("/users/222/follow", headers=A).status_code == 200
    assert c.post("/users/111/follow", headers=B).status_code == 200
    r = c.get("/me/nearby", headers=A).json()
    bob = r["people"][0]
    assert bob["mutual"] is True, bob
    assert abs(bob["lat"] - PB["lat"]) < 1e-6, bob
    assert abs(bob["lon"] - PB["lon"]) < 1e-6, bob
    assert 180 <= bob["distance_m"] <= 220, bob

    # Bob turns sharing off -> gone, and his stored fix is deleted
    r = c.post("/me/location", headers=B,
               json={"lat": 0, "lon": 0, "share": False})
    assert r.json()["sharing"] is False
    r = c.get("/me/nearby", headers=A).json()
    assert r["people"] == [], r
    r = c.get("/me/nearby", headers=B).json()
    assert r["sharing"] is False, r

print("server behaviour OK")
print("PHASE 78 OK")
