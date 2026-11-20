import hashlib, hmac, json, os, re, subprocess, sys, tempfile, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase149.db"
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
"""Phase-149 tests: Nearby Street View via Mapillary (free).

Owner decision (2026-11-19 10:47 Dhaka, after Phase 148 went
live): Mapillary (free, no card) over Google Street View (needs
a Google Cloud card + billing — the owner has no international
card). Build the Mapillary route only.

The feature: in Nearby, tapping a member pin (or the "You are
here" pin) opens the existing popup; a new "Street View"
button opens a FULL-SCREEN street-level viewer for the NEAREST
Mapillary photo to that point (Graph API radius search, 50 m,
bbox fallback). No photo nearby -> one honest line. Token: a
free read-only CLIENT token from mapillary.com/dashboard/
developers, env var MAPILLARY_CLIENT_TOKEN, carried to the
client via /auth as me.mapillary_client_token (empty = not set
up yet). No token value is committed anywhere.

WebGL fallback (the point of the phase): MapillaryJS renders
with WebGL and the owner's phone most likely fails WebGL (the
Phase 147 3D diagnosis). When the interactive viewer cannot
start, the nearest photo shows as a plain image instead — a
Street View that silently fails on his phone exactly like 3D
did would be a failed phase.

Covers: overlay markup + vendored MapillaryJS 4.1.2; popup
buttons in both engines + the me popup in both engines; client
markers; token plumbing (/auth empty + set, config default);
CSP hosts; backup still 42 tables; no token committed; node
harness runs the real SV helpers with stubs (lookup shape,
bbox fallback, nearest pick, attribution, token-missing,
no-imagery, WebGL-static fallback, viewer success, viewer
failure, close teardown); ?v=157 x9, no old-version literals; neighbouring
markers intact.
"""
CSS = open("webapp/style.css").read()
MAIN = open("app/main.py").read()
BOT = open("app/bot.py").read()
CFG = open("app/config.py").read()
VJS = open("webapp/vendor/mapillary/mapillary.js", "rb").read()
VCS = open("webapp/vendor/mapillary/mapillary.css", "rb").read()
assert len(VJS) == 1092073, len(VJS)
assert hashlib.md5(VJS).hexdigest() == "f5e8228c60e3367d3e6ba5345c905d58"
assert len(VCS) == 91456, len(VCS)
assert hashlib.md5(VCS).hexdigest() == "ce6ec8c4e4d5b4098929cc60b95ecdce"
print("vendored MapillaryJS 4.1.2 md5 + sizes OK")

# 1. Markup: the full-screen overlay + all its parts, hidden by
# default, inside the Nearby view after the map box.
for _id in ("streetview", "sv-title", "sv-close", "sv-viewer",
            "sv-photo", "sv-note", "sv-credit", "sv-mapillary-link"):
    assert f'id="{_id}"' in HTML, _id
assert 'id="streetview" class="sv-overlay" hidden' in HTML
assert HTML.index('id="streetview"') > HTML.index('id="nearby-map"')
assert HTML.index('id="streetview"') < HTML.index('id="nearby-list"')
assert 'vendor/mapillary/mapillary.js?v=157' in HTML
assert 'vendor/mapillary/mapillary.css?v=157' in HTML
assert 'View on Mapillary' in HTML
print("Street View overlay markup OK")

# 2. Client markers: helpers, lookup shape, honest states.
for m in ("nbSVOpen", "nbSVClose", "nbSVLookup", "nbSVPickNearest",
          "nbSVCanInteractive", "nbSVWebGL", "nbSVToken",
          "nbSVAttribution", "nbSVShowStatic", "nbSVShowNote",
          "nbSVHideNote", "nbFetchTimeout", "NB_SV_GRAPH",
          "NB_SV_FIELDS", "nbSVViewer",
          "https://graph.mapillary.com/images",
          "id,computed_geometry,thumb_1024_url,thumb_512_url,captured_at,creator,is_pano",
          "&radius=50&limit=5", "&bbox=", "&limit=10",
          "thumb_1024_url", "thumb_512_url",
          "© Mapillary contributors", "View on Mapillary",
          "https://www.mapillary.com/app/?pKey=",
          "Street View isn't set up yet — the Mapillary token is missing.",
          "No street-level photo here yet.",
          "Interactive view needs WebGL on this phone — showing the photo instead.",
          "Looking for a street-level photo…",
          "data-nb-streetview", "svCloseBtn.onclick = nbSVClose;",
          "component: { cover: false }", "viewer.moveTo(",
          "new Promise(res => setTimeout(() => res(false), 10000))",
          "viewer.remove()"):
    assert m in JS, m
# The me popups (both engines) and the member popup carry it.
assert 'data-nb-streetview=\\"me\\"' in JS
assert 'data-nb-streetview="' in JS
assert 'nbMLMe.getPopup().on("open"' in JS
print("149 client markers OK")

# 3. Style: the overlay rules + the [hidden] guards (display:flex
# would beat the hidden attribute without them).
for m in (".sv-overlay", ".sv-overlay[hidden]", ".sv-viewer[hidden]",
          ".sv-photo[hidden]", ".sv-note[hidden]", ".sv-head",
          ".sv-close", ".sv-photo", ".sv-note", ".sv-credit"):
    assert m in CSS, m
print("Street View style OK")

# 4. Menu-button URL versioning (bot.py, start_bot only).
assert 'menu_url.rstrip("/") + "/?v=157"' in BOT
assert "web_app=WebAppInfo(url=menu_url)" in BOT
assert BOT.count("WebAppInfo(url=settings.WEBAPP_URL)") == 1
print("menu-button URL versioning OK")

# 5. Token plumbing: config default + /auth empty and set.
assert "MAPILLARY_CLIENT_TOKEN" in CFG
assert 'os.environ.get("MAPILLARY_CLIENT_TOKEN", "")' in CFG
assert '"mapillary_client_token": settings.MAPILLARY_CLIENT_TOKEN,' in MAIN
with TestClient(app) as c:
    for h in (ALICE, BOB):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200
    import app.config as cfg
    assert cfg.settings.MAPILLARY_CLIENT_TOKEN == ""
    r = c.post("/auth", json={"initData": ALICE["X-Init-Data"]}).json()
    assert r.get("mapillary_client_token") == "", r
    cfg.settings.MAPILLARY_CLIENT_TOKEN = "TESTTOKEN123"
    try:
        r = c.post("/auth", json={"initData": ALICE["X-Init-Data"]}).json()
        assert r.get("mapillary_client_token") == "TESTTOKEN123", r
    finally:
        cfg.settings.MAPILLARY_CLIENT_TOKEN = ""
    print("token plumbing (/auth empty + set) OK")

    # 6. CSP header carries the Mapillary hosts (+ the 3D hosts).
    r = c.get("/health")
    assert r.status_code == 200, r.text
    csp = r.headers.get("Content-Security-Policy", "")
    assert "https://graph.mapillary.com" in csp, csp
    assert "https://images.mapillary.com" in csp, csp
    assert "worker-src 'self' blob:;" in csp, csp
    assert "tiles.openfreemap.org" in csp, csp
    print("CSP header served live OK")

    # 7. Backup still 42 tables (no schema change).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 43, len(r.json()["tables"])
    print("backup: 42 tables OK")

# 8. No Mapillary token value committed anywhere (the client
# token is shaped like MLY|... — it must only ever live in the
# Render env var, never in the repo).
for _root, _dirs, _files in list(os.walk("webapp")) + list(os.walk("app")):
    if "vendor" in _root:
        continue
    for _fn in _files:
        _p = os.path.join(_root, _fn)
        assert "MLY|" not in open(_p, errors="ignore").read(), _p
print("no Mapillary token committed OK")


# 9. Node harness: run the real SV helpers from app.js with stubs.
def _slice(name):
    start = JS.index("function " + name)
    end = JS.index("\n}\n", start) + len("\n}\n")
    return JS[start:end]


def _slice_async(name):
    start = JS.index("async function " + name)
    end = JS.index("\n}\n", start) + len("\n}\n")
    return JS[start:end]


def _slice_line(name):
    start = JS.index("function " + name)
    end = JS.index("\n", start) + 1
    return JS[start:end]


helpers = "\n".join((
    _slice("nbSVToken() {"),
    _slice("nbSVWebGL() {"),
    _slice("nbSVCanInteractive() {"),
    _slice("nbSVPickNearest(lat, lon, imgs) {"),
    _slice("nbFetchTimeout(url, ms) {"),
    _slice_async("nbSVLookup(lat, lon) {"),
    _slice("nbSVAttribution(img) {"),
    _slice("nbSVShowNote(t) {"),
    _slice_line("nbSVHideNote() {"),
    _slice("nbSVShowStatic(img, why) {"),
    _slice_async("nbSVOpen(lat, lon, label) {"),
    _slice("nbSVClose() {"),
))
for fn in ("function nbSVToken() {", "function nbSVWebGL() {",
           "function nbSVCanInteractive() {",
           "function nbSVPickNearest(lat, lon, imgs) {",
           "function nbFetchTimeout(url, ms) {",
           "async function nbSVLookup(lat, lon) {",
           "function nbSVAttribution(img) {",
           "function nbSVShowNote(t) {",
           "function nbSVHideNote() {",
           "function nbSVShowStatic(img, why) {",
           "async function nbSVOpen(lat, lon, label) {",
           "function nbSVClose() {"):
    assert fn in helpers, fn

harness = """
let me = { mapillary_client_token: "TESTTOKEN" };
let nbSVViewer = null;
const NB_SV_GRAPH = "https://graph.mapillary.com/images";
const NB_SV_FIELDS = "id,computed_geometry,thumb_1024_url,thumb_512_url,captured_at,creator,is_pano";
function makeEl() {
  return { hidden: true, textContent: "", innerHTML: "", src: "", href: "",
    style: {}, onclick: null,
    removeAttribute: function () {}, setAttribute: function () {},
    classList: { add: function () {}, remove: function () {}, toggle: function () {} } };
}
let els = {};
["streetview", "sv-title", "sv-close", "sv-viewer", "sv-photo",
 "sv-note", "sv-credit", "sv-mapillary-link"].forEach(id => els[id] = makeEl());
function $(id) { return els[id] || null; }
let webglAvailable = true;
let document = { createElement: function (tag) {
  if (tag === "canvas") return { getContext: function () { return webglAvailable ? {} : null; } };
  return {};
} };
let fetchCalls = [];
let fetchBehavior = "radius-hit";
let radiusImgs = [
  { id: "111", computed_geometry: { type: "Point", coordinates: [90.4126, 23.8104] },
    thumb_1024_url: "https://images.mapillary.com/111/thumb-1024.jpg",
    thumb_512_url: "https://images.mapillary.com/111/thumb-512.jpg",
    captured_at: 1700000000000, creator: { username: "dhaka-walker" }, is_pano: true },
  { id: "222", computed_geometry: { type: "Point", coordinates: [90.42, 23.82] },
    thumb_1024_url: "https://images.mapillary.com/222/thumb-1024.jpg",
    captured_at: 1690000000000, creator: "anon-shooter", is_pano: false }
];
let bboxImgs = [
  { id: "333", geometry: { type: "Point", coordinates: [90.4135, 23.8110] },
    thumb_1024_url: "https://images.mapillary.com/333/thumb-1024.jpg",
    captured_at: 1710000000000, creator: { username: "mapper-7" }, is_pano: false }
];
function fetch(url) {
  fetchCalls.push(url);
  let data;
  if (url.indexOf("lat=") !== -1) {
    if (fetchBehavior === "radius-hit") data = { data: radiusImgs };
    else if (fetchBehavior === "radius-empty-bbox-hit" || fetchBehavior === "empty") data = { data: [] };
    else return Promise.reject(new Error("net down"));
  } else {
    if (fetchBehavior === "radius-empty-bbox-hit") data = { data: bboxImgs };
    else if (fetchBehavior === "empty") data = { data: [] };
    else return Promise.reject(new Error("net down"));
  }
  return Promise.resolve({ json: function () { return Promise.resolve(data); } });
}
let timers = [];
function setTimeout(fn, ms) { timers.push({ fn: fn, ms: ms }); return timers.length; }
function clearTimeout(id) {}
function drainTimers(ms) { timers.filter(t => t.ms === ms).forEach(t => t.fn()); }
let viewerBehavior = "ok";
let viewerInstances = [];
let removedViewers = 0;
function FakeViewer(opts) { this.opts = opts; viewerInstances.push(this); }
FakeViewer.prototype.moveTo = function (id) {
  if (viewerBehavior === "ok") return Promise.resolve();
  if (viewerBehavior === "reject") return Promise.reject(new Error("bad token"));
  return new Promise(() => {});
};
FakeViewer.prototype.remove = function () { removedViewers++; };
let mapillary = { Viewer: FakeViewer };
function check(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function resetSV() {
  me = { mapillary_client_token: "TESTTOKEN" };
  webglAvailable = true; fetchBehavior = "radius-hit"; viewerBehavior = "ok";
  fetchCalls = []; timers = []; viewerInstances = []; removedViewers = 0;
  nbSVViewer = null;
  Object.keys(els).forEach(id => { els[id] = makeEl(); });
}
""" + helpers + """
(async () => {
// (a) pick nearest: computed_geometry wins, geometry fallback,
// images without geometry skipped.
let pick = nbSVPickNearest(23.8103, 90.4125, radiusImgs);
check(pick && pick.id === "111", "nearest is 111, got " + (pick && pick.id));
pick = nbSVPickNearest(23.8103, 90.4125, [{ id: "x" }, bboxImgs[0]]);
check(pick && pick.id === "333", "geometry fallback + skip missing geometry");
check(nbSVPickNearest(23.81, 90.41, []) === null, "empty -> null");
// (b) attribution: creator object, creator string, none; date.
let att = nbSVAttribution(radiusImgs[0]);
check(att.text.indexOf("© Mapillary contributors") === 0, "credit prefix");
check(att.text.indexOf("dhaka-walker") !== -1, "creator username in credit");
check(att.text.indexOf("2023-11-14") !== -1, "captured date in credit, got " + att.text);
check(att.link === "https://www.mapillary.com/app/?pKey=111", "mapillary link");
att = nbSVAttribution(radiusImgs[1]);
check(att.text.indexOf("anon-shooter") !== -1, "creator string in credit");
att = nbSVAttribution({ id: "9" });
check(att.text === "© Mapillary contributors", "bare credit when no creator/date");
// (c) radius query shape + nearest via lookup.
resetSV();
let img = await nbSVLookup(23.8103, 90.4125);
check(fetchCalls.length === 1, "one call for radius hit, got " + fetchCalls.length);
check(fetchCalls[0].indexOf("https://graph.mapillary.com/images?") === 0, "graph host");
check(fetchCalls[0].indexOf("lat=23.8103") !== -1 && fetchCalls[0].indexOf("lng=90.4125") !== -1, "lat/lng params");
check(fetchCalls[0].indexOf("radius=50") !== -1, "radius=50");
check(fetchCalls[0].indexOf("limit=5") !== -1, "limit=5");
check(fetchCalls[0].indexOf("access_token=TESTTOKEN") !== -1, "token param");
check(fetchCalls[0].indexOf("fields=id,computed_geometry,thumb_1024_url") !== -1, "fields param");
check(img && img.id === "111", "lookup returns nearest 111");
// (d) bbox fallback when the radius is empty.
resetSV(); fetchBehavior = "radius-empty-bbox-hit";
img = await nbSVLookup(23.8103, 90.4125);
check(fetchCalls.length === 2, "radius + bbox calls, got " + fetchCalls.length);
check(fetchCalls[1].indexOf("bbox=") !== -1 && fetchCalls[1].indexOf("lat=") === -1, "bbox call has no lat");
check(img && img.id === "333", "bbox fallback returns nearest 333");
// (e) token missing -> lookup short-circuits, no fetch.
resetSV(); me = { mapillary_client_token: "" };
img = await nbSVLookup(23.8103, 90.4125);
check(img === null && fetchCalls.length === 0, "no token -> no fetch");
// (f) open with no token -> honest note, overlay visible, no fetch, no viewer.
resetSV(); me = { mapillary_client_token: "" };
await nbSVOpen(23.8103, 90.4125, "Amina");
check(els["streetview"].hidden === false, "overlay opens even without token");
check(els["sv-note"].hidden === false && els["sv-note"].textContent.indexOf("isn't set up yet") !== -1, "token-missing note, got " + JSON.stringify(els["sv-note"].textContent));
check(fetchCalls.length === 0 && viewerInstances.length === 0, "no fetch, no viewer without token");
check(els["sv-title"].textContent === "Street View — Amina", "title carries the name");
// (g) open with no imagery -> honest note, no viewer, no photo.
resetSV(); fetchBehavior = "empty";
await nbSVOpen(23.8103, 90.4125, "Babu");
check(els["sv-note"].hidden === false && els["sv-note"].textContent.indexOf("No street-level photo here yet.") !== -1, "no-imagery note");
check(viewerInstances.length === 0 && els["sv-photo"].hidden === true, "no viewer, no photo when empty");
// (h) WebGL unavailable -> static photo + WebGL note, no viewer.
resetSV(); webglAvailable = false;
await nbSVOpen(23.8103, 90.4125, "Chitra");
check(viewerInstances.length === 0, "no viewer without WebGL");
check(els["sv-photo"].hidden === false && els["sv-photo"].src === "https://images.mapillary.com/111/thumb-1024.jpg", "static photo src, got " + els["sv-photo"].src);
check(els["sv-note"].hidden === false && els["sv-note"].textContent.indexOf("WebGL") !== -1, "WebGL note on static fallback");
check(els["sv-credit"].textContent.indexOf("dhaka-walker") !== -1, "attribution on static fallback");
check(els["sv-mapillary-link"].href === "https://www.mapillary.com/app/?pKey=111", "mapillary link on static fallback");
// (h2) library missing -> static photo too.
resetSV(); mapillary = undefined;
await nbSVOpen(23.8103, 90.4125, "Hana");
check(viewerInstances.length === 0, "no viewer without the library");
check(els["sv-photo"].hidden === false, "static photo when library missing");
mapillary = { Viewer: FakeViewer };
// (i) WebGL available + viewer loads -> interactive, note hidden.
resetSV();
await nbSVOpen(23.8103, 90.4125, "Dina");
check(viewerInstances.length === 1, "viewer created");
check(viewerInstances[0].opts.imageId === "111", "viewer imageId is nearest");
check(viewerInstances[0].opts.accessToken === "TESTTOKEN", "viewer token");
check(viewerInstances[0].opts.component.cover === false, "cover off");
check(els["sv-note"].hidden === true, "note hidden when viewer loads");
check(els["sv-viewer"].hidden === false, "viewer box visible");
// (j) viewer moveTo rejects -> static fallback, viewer removed.
resetSV(); viewerBehavior = "reject";
await nbSVOpen(23.8103, 90.4125, "Emon");
check(viewerInstances.length === 1 && removedViewers === 1, "failed viewer removed");
check(els["sv-photo"].hidden === false && els["sv-photo"].src.indexOf("111/thumb-1024") !== -1, "static fallback after viewer error");
// (k) viewer hangs past 10 s -> timeout fires, static fallback.
resetSV(); viewerBehavior = "hang";
let p = nbSVOpen(23.8103, 90.4125, "Farah");
await new Promise(r => setImmediate(r));
await new Promise(r => setImmediate(r));
drainTimers(10000);
await p;
check(viewerInstances.length === 1 && removedViewers === 1, "hung viewer removed after timeout");
check(els["sv-photo"].hidden === false, "static fallback after viewer timeout");
// (l) close tears everything down, map state untouched.
resetSV();
await nbSVOpen(23.8103, 90.4125, "Gita");
check(els["streetview"].hidden === false, "overlay open before close");
nbSVClose();
check(removedViewers === 1, "viewer removed on close");
check(els["streetview"].hidden === true, "overlay hidden after close");
check(els["sv-photo"].hidden === true && els["sv-photo"].src === "", "photo cleared after close");
check(els["sv-note"].hidden === true, "note cleared after close");
check(els["sv-viewer"].hidden === true && els["sv-viewer"].innerHTML === "", "viewer box cleared after close");
console.log("NODE HARNESS OK");
})().catch(e => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(harness)
    hpath = f.name
r = subprocess.run(["node", hpath], capture_output=True, text=True)
os.unlink(hpath)
print(r.stdout.strip())
assert r.returncode == 0, r.stderr or r.stdout
print("node harness: 149 helpers OK")

# 10. Client markers + asset version.
assert HTML.count("?v=157") == 10, HTML.count("?v=157")
assert "?v=14" + "8" not in HTML
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
          "followedTags", "/me/hashtags", "/feed/hashtags",
          "nbInit3D", "nbInit2D", "nbCan3D", "nbDrawRoute3D",
          "nbClearRoute3D", "nbFitRoute3D", "nbGoTo",
          "nbOpenPersonPopup", "nbWirePopupEl", "nbMLEl", "nbMLMeEl",
          "nbMePinHTML", "nx_nb_mode", "nb3DFailed",
          "NB_3D_STYLE", "NB_3D_PITCH",
          "tiles.openfreemap.org/styles/liberty",
          "maplibregl.supported()", "setTimeout(fail, 12000)",
          "map.once(\"load\"", "map.on(\"error\"",
          "nb3DWhy", "nbPaint3DNote", "nbPaintModeBtn",
          "Try 3D", "NB_3D_NOTES"):
    assert m in JS, m
print("client markers + ?v=157 OK")

print("PHASE-149 TESTS PASSED")
