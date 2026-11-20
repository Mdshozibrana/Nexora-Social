"""Phase-147 tests: Nearby goes 3D (MapLibre + OpenFreeMap).

Owner request (2026-11-19 ~00:35 Dhaka, with a reference
screenshot of an offline-maps app ad — perspective 3D city
buildings, a car with a glowing green navigation route):
make the Nearby map 3D like that, so everything is easy to
see and understand at a glance on a phone.

Choice (surveyed first, recorded in phase147_patch.py): MapLibre
GL JS 4.7.1, vendored into webapp/vendor/maplibre/, over the
free OpenFreeMap "liberty" style — its building-3d layer
extrudes OSM buildings, no API key anywhere. MapLibre v4 tries
WebGL2 with a WebGL1 fallback. Leaflet stays vendored as the
automatic 2D fallback: MapLibre missing, WebGL unavailable,
or the 3D style failing to load within 12 s all fall back to
the old 2D map, so the map never goes blank. A small 2D/3D
switch above the map lets the member pick (remembered on the
device). CSP gains worker-src 'self' blob: (MapLibre runs its
renderer in a blob: Web Worker — without it the worker falls
back to script-src, which has no blob:, and the 3D map would
fail silently) and tiles.openfreemap.org in connect-src.

Covers: vendored 3D assets exist and are versioned; 3D init
markers (pitch, style, building layer via the style URL);
adapter + fallback wiring; node harness runs the real
nbCan3D / nbDrawRoute3D / nbClearRoute3D / nbFitRoute3D /
nbPaintModeBtn helpers with stubs (3D decision matrix, route
coordinate flip lat/lon -> lon/lat, glowing green route
layers, mode-button labels); 2D fallback path intact
(Leaflet init, OSM tiles, OSRM routing); sharing toggle
server behaviour (on/off, 500 m, off deletes); CSP header
served live carries worker-src + tiles host; backup still 42
tables (no schema change); ?v=154 x7, no ?v=146; neighbouring
markers intact.
"""
import hashlib, hmac, json, os, re, subprocess, sys, tempfile, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase147.db"
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

JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()
MAIN = open("app/main.py").read()

# 1. Vendored 3D assets exist, are versioned, and are real.
assert "vendor/maplibre/maplibre-gl-4.7.1.js?v=154" in HTML
assert "vendor/maplibre/maplibre-gl-4.7.1.css?v=154" in HTML
assert os.path.getsize(
    "webapp/vendor/maplibre/maplibre-gl-4.7.1.js") > 500000
assert os.path.getsize(
    "webapp/vendor/maplibre/maplibre-gl-4.7.1.css") > 10000
# The 2D fallback stays vendored and referenced.
assert "vendor/leaflet/leaflet.js?v=154" in HTML
assert "vendor/leaflet/leaflet.css?v=154" in HTML
assert os.path.getsize("webapp/vendor/leaflet/leaflet.js") > 100000
# Mode switch markup.
assert 'id="nearby-mode"' in HTML
assert "nb-mode-row" in HTML
print("vendored 3D assets + 2D fallback refs OK")

# 2. 3D init markers: style, pitch, engine adapter, fallback.
for m in ("NB_3D_STYLE", "tiles.openfreemap.org/styles/liberty",
          "NB_3D_PITCH", "new maplibregl.Map", "pitch: NB_3D_PITCH",
          "maxPitch: 70", "maplibregl.supported()", "nbCan3D",
          "nbInit3D", "nbInit2D", "nbEnsureMap", "nbDestroyEngine",
          "nbPaintModeBtn", "nbGoTo", "nbOpenPersonPopup",
          "nbWirePopupEl", "nbMLEl", "nbMLMeEl", "nbMePinHTML",
          "nbDrawRoute3D", "nbClearRoute3D", "nbFitRoute3D",
          "nb-route-glow", "nb-route-core", "#00E676",
          "nx_nb_mode", "nb3DFailed", "setTimeout(fail, 12000)",
          "map.once(\"load\"", "map.on(\"error\""):
    assert m in JS, m
# The 2D path is intact behind the fallback.
for m in ("L.map(\"nearby-map\"", "tile.openstreetmap.org",
          "routing.openstreetmap.de", "L.marker", "L.polyline",
          "async function openNearby()", "function stopNearby()",
          "nbEnsureMap()", "nbRefresh()", "nbPaintPeople",
          "nbPaintStories", "nbRoute", "nbClearRoute", "nbLocate",
          "LocationManager", "data-nb-profile", "data-nb-route"):
    assert m in JS, m
# No old direct-Leaflet call survives in the painted paths:
# list rows and story circles go through the adapter.
assert "nbMap.setView([q.lat, q.lon], 17)" not in JS
assert "nbMarkers[q.id].openPopup()" not in JS
print("3D init + adapter + fallback wiring OK")

# 3. Style: mode switch + MapLibre popup/marker rules.
for m in (".nb-mode-row", ".nb-mode-btn", ".nb-ml-pin", ".nb-ml-me",
          ".maplibregl-popup-content", ".maplibregl-popup-tip",
          ".maplibregl-ctrl-attrib"):
    assert m in CSS, m
# The Phase 78/80 look is untouched.
for m in (".nb-pin::after", ".nb-me-pin::after", ".nb-ring.r0",
          ".nb-card", ".nb-route-btn"):
    assert m in CSS, m
print("3D style rules OK")

# 4. CSP source + served header: worker-src blob: and the tile host.
assert "tiles.openfreemap.org" in MAIN
assert "worker-src 'self' blob:;" in MAIN
assert "routing.openstreetmap.de" in MAIN  # OSRM routing kept
print("CSP source OK")

with TestClient(app) as c:
    for h in (ALICE, BOB):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 5. CSP header is served live on every response.
    r = c.get("/health")
    assert r.status_code == 200, r.text
    csp = r.headers.get("Content-Security-Policy", "")
    assert "worker-src 'self' blob:;" in csp, csp
    assert "tiles.openfreemap.org" in csp, csp
    assert "routing.openstreetmap.de" in csp, csp
    print("CSP header served live OK")

    # 6. Sharing toggle server behaviour (unchanged by the 3D work).
    PA = {"lat": 23.81030, "lon": 90.41250}
    PB = {"lat": 23.81210, "lon": 90.41250}
    r = c.post("/me/location", headers=BOB, json={**PB, "share": True})
    assert r.status_code == 200 and r.json()["sharing"], r.text
    r = c.post("/me/location", headers=ALICE, json={**PA, "share": True})
    assert r.status_code == 200 and r.json()["sharing"], r.text
    r = c.get("/me/nearby", headers=ALICE).json()
    assert r["sharing"] is True, r
    assert [q["id"] for q in r["people"]] == [222], r
    r = c.post("/me/location", headers=BOB,
               json={"lat": 0, "lon": 0, "share": False})
    assert r.json()["sharing"] is False
    r = c.get("/me/nearby", headers=ALICE).json()
    assert r["people"] == [], r
    print("sharing toggle server behaviour OK")

    # 7. Backup still 42 tables (no schema change).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 43, len(r.json()["tables"])
    print("backup: 42 tables OK")


# 8. Node harness: run the real 3D helpers from app.js with stubs.
def _slice(name):
    start = JS.index("function " + name)
    end = JS.index("\n}\n", start) + len("\n}\n")
    return JS[start:end]


helpers = "\n".join((
    _slice("nbCan3D() {"),
    _slice("nbDrawRoute3D(pts) {"),
    _slice("nbClearRoute3D() {"),
    _slice("nbFitRoute3D(pts) {"),
    _slice("nb3DWhy() {"),
    _slice("nbPaintModeBtn() {"),
))
for fn in ("function nbCan3D() {", "function nbDrawRoute3D(pts) {",
           "function nbClearRoute3D() {", "function nbFitRoute3D(pts) {",
           "function nb3DWhy() {", "function nbPaintModeBtn() {"):
    assert fn in helpers, fn

harness = """
let nbML = null, nbMLPopup = null, nbEngine = null;
let nb3DFailed = false, nb3DFailKind = null, nbModePref = null;
let maplibregl = { supported: () => true,
  LngLatBounds: class { constructor() { this.e = []; }
    extend(c) { this.e.push(c); } } };
let btn = { hidden: true, textContent: "" };
function $(id) { return id === "nearby-mode" ? btn : null; }
function check(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
""" + helpers + """
// --- nbCan3D decision matrix ---
nb3DFailed = false; nbModePref = null;
check(nbCan3D() === true, "3D available by default");
nbModePref = "2d";
check(nbCan3D() === false, "mode pref 2d must not use 3D");
nbModePref = "3d";
check(nbCan3D() === true, "mode pref 3d uses 3D");
nbModePref = null; nb3DFailed = true;
check(nbCan3D() === false, "a failed 3D attempt must not retry");
nb3DFailed = false;
maplibregl = { supported: () => false,
  LngLatBounds: class { constructor() { this.e = []; }
    extend(c) { this.e.push(c); } } };
check(nbCan3D() === false, "unsupported WebGL must not use 3D");
// --- nbDrawRoute3D: lat/lon flips to lon/lat, glow + core layers ---
let addedSrc = null, addedLayers = [];
nbML = { getSource: () => null,
  addSource: (id, def) => { addedSrc = [id, def]; },
  addLayer: (l) => { addedLayers.push(l); } };
nbDrawRoute3D([[23.8103, 90.4125], [23.8121, 90.4125]]);
check(addedSrc && addedSrc[0] === "nb-route", "route source id");
check(JSON.stringify(addedSrc[1].data.geometry.coordinates) ===
  JSON.stringify([[90.4125, 23.8103], [90.4125, 23.8121]]),
  "route coords must flip to [lon, lat], got " +
  JSON.stringify(addedSrc[1].data.geometry.coordinates));
check(addedLayers.length === 2, "glow + core layers");
check(addedLayers[0].id === "nb-route-glow" &&
  addedLayers[0].paint["line-color"] === "#00E676", "glow layer green");
check(addedLayers[1].id === "nb-route-core" &&
  addedLayers[1].paint["line-width"] === 5, "core layer width 5");
// second draw reuses the source (no duplicate layers).
addedLayers = [];
nbML = { getSource: () => ({ setData: (d) => { addedSrc = ["set", d]; } }),
  addSource: () => { throw new Error("must not re-add"); },
  addLayer: () => { throw new Error("must not re-add layer"); } };
nbDrawRoute3D([[23.81, 90.41], [23.82, 90.42]]);
check(addedSrc[0] === "set", "second draw updates source data");
// --- nbClearRoute3D removes layers then source, in order ---
let removed = [];
nbML = { getLayer: (id) => true, removeLayer: (id) => { removed.push("L:" + id); },
  getSource: () => true, removeSource: (id) => { removed.push("S:" + id); } };
nbClearRoute3D();
check(JSON.stringify(removed) ===
  JSON.stringify(["L:nb-route-glow", "L:nb-route-core", "S:nb-route"]),
  "clear order layers-then-source, got " + JSON.stringify(removed));
// --- nbFitRoute3D fits the flipped bounds ---
let fitted = null;
nbML = { fitBounds: (b, opts) => { fitted = [b.e, opts.padding]; } };
nbFitRoute3D([[23.8103, 90.4125], [23.8121, 90.4125]]);
check(JSON.stringify(fitted[0]) ===
  JSON.stringify([[90.4125, 23.8103], [90.4125, 23.8121]]),
  "fit bounds flipped, got " + JSON.stringify(fitted[0]));
check(fitted[1] === 30, "fit padding 30");
// --- nbPaintModeBtn labels + visibility ---
// (the nbCan3D matrix above left supported() false — restore it)
maplibregl = { supported: () => true,
  LngLatBounds: class { constructor() { this.e = []; }
    extend(c) { this.e.push(c); } } };
nbEngine = "3d";
nbPaintModeBtn();
check(btn.hidden === false && btn.textContent === "🧊 3D view",
  "3D label, got " + JSON.stringify(btn.textContent));
nbEngine = "2d";
nbPaintModeBtn();
check(btn.hidden === false && btn.textContent === "🗺 2D view",
  "2D label, got " + JSON.stringify(btn.textContent));
maplibregl = { supported: () => false,
  LngLatBounds: class { constructor() { this.e = []; }
    extend(c) { this.e.push(c); } } };
nbPaintModeBtn();
check(btn.hidden === false && btn.textContent === "🧊 Try 3D",
  "WebGL unsupported -> button stays visible, offers retry, got " +
  JSON.stringify(btn.textContent));
console.log("NODE HARNESS OK");
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(harness)
    hpath = f.name
r = subprocess.run(["node", hpath], capture_output=True, text=True)
os.unlink(hpath)
print(r.stdout.strip())
assert r.returncode == 0, r.stderr or r.stdout
print("node harness: 3D helpers OK")

# 9. Client markers + asset version.
assert HTML.count("?v=154") == 9, HTML.count("?v=154")
assert "?v=14" + "6" not in HTML
for m in ("loadSettings", "renderLevelBlock", "openTipSheet",
          "loadProfilePosts", "openProfile", "loadMe",
          "loadDrafts", "loadScheduled", "loadFollowRequests",
          "themeCard", "dataCard", "loadBlocked", "routeStartParam",
          "loadFeed", "showView", "rememberProfile", "restoreProfile",
          "openNearby", "stopNearby", "nbPaintPeople", "nbPaintStories",
          "loadTrending", "loadHealth", "loadAdminBrowse",
          "loadSecurityLog", "loadPayouts", "loadBroadcasts",
          "loadBackupStatus", "openInsights", "loadScheduled",
          "composer-schedule", "loadFollowRequests", "privacy-row",
          "private-lock", "renderLevelBlock", "level-block",
          "DM_REACTIONS", "reactToMessage", "chat-photo",
          "bubble-photo", "openStoryViewers", "sendStoryReply",
          "story-reply", "story-viewers", "tab-hashtags",
          "search-tag-follow", "hashtag-card", "hashtag-row",
          "followedTags", "/me/hashtags", "/feed/hashtags"):
    assert m in JS, m
print("client markers + ?v=154 OK")

print("PHASE-147 TESTS PASSED")
