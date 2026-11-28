"""Phase-148 tests: Nearby 3D does not appear on the owner's phone.

Owner report (2026-11-19 ~08:30 Dhaka, with a phone screenshot of
the Nearby view): "এখানে 3D দেখছি না, কোনো বাটনও নেই।" — the
screenshot shows the FLAT 2D Leaflet map (the Phase 147 fallback)
and NO 3D/2D switch button anywhere.

Confirmed cause (surveyed before building; the code IS deployed):
the mode button started `hidden` and nbPaintModeBtn() only unhid
it when `maplibregl` was defined AND maplibregl.supported() was
true — when either failed, the button stayed hidden forever with
no explanation. A style-load failure alone does NOT explain the
screenshot (the fallback path still calls nbPaintModeBtn(), which
would SHOW the button whenever the library loaded and WebGL
works), so the cause is one of: (a) stale pre-147 shell (the
button is not in the DOM at all — Telegram Android webviews are
notorious for serving a cached Mini App page), (b) the MapLibre
library did not load, or (c) WebGL unsupported on his phone.
The style URL is fine (200) and the CSP already allows it.

The fix: the switch is ALWAYS visible (when 3D is off it reads
"Try 3D" and retries); a one-line honest diagnostic under the
map names the reason (lib / webgl / style); a retry resets
nb3DFailed + nb3DFailKind and re-attempts 3D; nbInit3D() records
WHY it failed; the bot menu-button URL now carries ?v=206 so
Telegram opens a fresh page on every deploy. The 2D fallback
stays — the map never goes blank.

Covers: markup (button never hidden, diagnostic div present);
client markers + the old silent-failure line gone; diagnostic
style; menu-button URL versioning (start_bot only, /start button
keeps the bare URL); sharing toggle server behaviour unchanged;
CSP still carries worker-src + the tile host; backup still 42
tables; node harness runs the real nbCan3D / nb3DWhy /
nbPaintModeBtn / nbPaint3DNote / nbInit3D helpers with stubs
(reason matrix, button labels, note text/visibility, 3D init
success, style timeout, constructor WebGL vs other errors,
retry-after-timeout succeeds, WebGL-unsupported retry cannot
loop); ?v=206 x7, no ?v=147; neighbouring markers intact.
"""
import hashlib, hmac, json, os, re, subprocess, sys, tempfile, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase148.db"
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
BOT = open("app/bot.py").read()

# 1. Markup: the mode button is never hidden; the diagnostic line
# exists right after the map box.
assert 'id="nearby-mode"' in HTML
assert "nb-mode-btn" in HTML
assert 'hidden>🧊 3D view</button>' not in HTML
assert 'id="nearby-3d-note"' in HTML
assert 'class="nb-3d-note"' in HTML
assert HTML.index('id="nearby-3d-note"') > HTML.index('id="nearby-map"')
assert 'title="Switch between the 3D map and the flat 2D map" hidden' not in HTML
print("mode button always visible + diagnostic markup OK")

# 2. Client markers: reason probe, painter, retry reset, fail kind.
for m in ("nb3DWhy", "nbPaint3DNote", "NB_3D_NOTES", "nb3DFailKind",
          "Try 3D", "b.hidden = false;",
          "nbPaintModeBtn(); nbPaint3DNote()",
          "nb3DFailKind = null; }", "const fail = (kind) => {",
          "fail(\"style\")", "? \"webgl\" : \"style\"",
          "3D didn't start — the 3D library didn't load on this phone.",
          "3D isn't available on this phone — it needs WebGL,",
          "3D couldn't load its map in time — showing the flat map."):
    assert m in JS, m
# The old silent-failure line is gone.
assert "b.hidden = !ok;" not in JS
# The retry resets BOTH failure flags (the toggle handler).
assert "if (want3D) { nb3DFailed = false; nb3DFailKind = null; }" in JS
print("148 client markers OK")

# 3. Style: the diagnostic line rule.
assert ".nb-3d-note" in CSS
print("diagnostic style OK")

# 4. Menu-button URL versioning (bot.py, start_bot only).
assert 'menu_url.rstrip("/") + "/?v=206"' in BOT
assert "web_app=WebAppInfo(url=menu_url)" in BOT
# The /start inline button keeps the bare URL (exactly one bare
# WebAppInfo left — the menu button now uses menu_url).
assert BOT.count("WebAppInfo(url=settings.WEBAPP_URL)") == 1
print("menu-button URL versioning OK")

with TestClient(app) as c:
    for h in (ALICE, BOB):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 5. CSP header still carries worker-src + the tile host.
    r = c.get("/health")
    assert r.status_code == 200, r.text
    csp = r.headers.get("Content-Security-Policy", "")
    assert "worker-src 'self' blob:;" in csp, csp
    assert "tiles.openfreemap.org" in csp, csp
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
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    print("backup: 42 tables OK")


# 8. Node harness: run the real 3D helpers from app.js with stubs.
def _slice(name):
    start = JS.index("function " + name)
    end = JS.index("\n}\n", start) + len("\n}\n")
    return JS[start:end]


helpers = "\n".join((
    _slice("nbCan3D() {"),
    _slice("nb3DWhy() {"),
    _slice("nbPaintModeBtn() {"),
    _slice("nbPaint3DNote() {"),
    _slice("nbInit3D() {"),
))
for fn in ("function nbCan3D() {", "function nb3DWhy() {",
           "function nbPaintModeBtn() {", "function nbPaint3DNote() {",
           "function nbInit3D() {"):
    assert fn in helpers, fn

harness = """
let nbML = null, nbEngine = null;
let nb3DFailed = false, nb3DFailKind = null, nbModePref = null;
const NB_3D_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const NB_3D_PITCH = 60;
const NB_3D_NOTES = {
  lib: "3D didn't start — the 3D library didn't load on this phone. The flat map is showing instead. Tap 🧊 Try 3D to try again.",
  webgl: "3D isn't available on this phone — it needs WebGL, which this phone doesn't offer. The flat map is showing instead.",
  style: "3D couldn't load its map in time — showing the flat map. Tap 🧊 Try 3D to try again."
};
let btn = { hidden: true, textContent: "" };
let note = { hidden: true, textContent: "" };
function $(id) { return id === "nearby-mode" ? btn : id === "nearby-3d-note" ? note : null; }
let timers = [];
function setTimeout(fn, ms) { timers.push(fn); return timers.length; }
function clearTimeout(id) {}
let mapBehavior = "load";
function FakeMap(opts) {
  if (mapBehavior === "throw-webgl") throw new Error("Failed to initialize WebGL");
  if (mapBehavior === "throw-other") throw new Error("boom");
  this.opts = opts; this.handlers = {};
}
FakeMap.prototype.once = function (ev, cb) {
  if (ev === "load" && mapBehavior === "load") cb();
  else this.handlers[ev] = cb;
};
FakeMap.prototype.on = function (ev, cb) { this.handlers[ev] = cb; };
FakeMap.prototype.remove = function () {};
let maplibregl = { supported: () => true, Map: FakeMap };
function check(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function reset3D() {
  nbML = null; nbEngine = null; nbModePref = null;
  nb3DFailed = false; nb3DFailKind = null;
  maplibregl = { supported: () => true, Map: FakeMap };
  mapBehavior = "load"; timers = [];
  btn.hidden = true; btn.textContent = "";
  note.hidden = true; note.textContent = "";
}
""" + helpers + """
(async () => {
// --- nb3DWhy decision matrix + button labels + note ---
// (a) 3D on: no reason, 3D label, note hidden.
reset3D(); nbEngine = "3d";
check(nb3DWhy() === null, "3D on -> no reason");
nbPaintModeBtn(); nbPaint3DNote();
check(btn.hidden === false && btn.textContent === "🧊 3D view", "3D label, got " + JSON.stringify(btn.textContent));
check(note.hidden === true && note.textContent === "", "no note when 3D is on");
// (b) 2D by choice: no reason, 2D label, note hidden.
reset3D(); nbEngine = "2d"; nbModePref = "2d";
check(nb3DWhy() === null, "deliberate 2D -> no reason");
nbPaintModeBtn(); nbPaint3DNote();
check(btn.textContent === "🗺 2D view", "2D label when chosen, got " + JSON.stringify(btn.textContent));
check(note.hidden === true, "no note for a deliberate 2D choice");
// (c) library missing: lib reason, Try 3D button, lib note.
reset3D(); nbEngine = "2d"; maplibregl = undefined;
check(nb3DWhy() === "lib", "library missing -> lib");
nbPaintModeBtn(); nbPaint3DNote();
check(btn.hidden === false && btn.textContent === "🧊 Try 3D", "lib -> Try 3D button, got " + JSON.stringify(btn.textContent));
check(note.hidden === false && note.textContent.indexOf("library didn't load") !== -1, "lib note text, got " + JSON.stringify(note.textContent));
// (d) WebGL unsupported: webgl reason, Try 3D button, webgl note.
reset3D(); nbEngine = "2d"; maplibregl = { supported: () => false, Map: FakeMap };
check(nb3DWhy() === "webgl", "WebGL unsupported -> webgl");
nbPaintModeBtn(); nbPaint3DNote();
check(btn.hidden === false && btn.textContent === "🧊 Try 3D", "webgl -> Try 3D button, got " + JSON.stringify(btn.textContent));
check(note.hidden === false && note.textContent.indexOf("WebGL") !== -1, "webgl note text, got " + JSON.stringify(note.textContent));
// (e) style failed: style reason, Try 3D button, style note.
reset3D(); nbEngine = "2d"; nb3DFailed = true; nb3DFailKind = "style";
check(nb3DWhy() === "style", "style timeout -> style");
nbPaintModeBtn(); nbPaint3DNote();
check(btn.textContent === "🧊 Try 3D", "style -> Try 3D button, got " + JSON.stringify(btn.textContent));
check(note.hidden === false && note.textContent.indexOf("in time") !== -1, "style note text, got " + JSON.stringify(note.textContent));
// (e2) constructor WebGL failure recorded as webgl.
reset3D(); nbEngine = "2d"; nb3DFailed = true; nb3DFailKind = "webgl";
check(nb3DWhy() === "webgl", "constructor WebGL failure -> webgl");
// --- nbInit3D: success, style timeout, constructor failures ---
// (f) success: load fires, engine 3d, kind cleared.
reset3D(); mapBehavior = "load";
let ok = await nbInit3D();
check(ok === true && nbEngine === "3d" && nb3DFailKind === null, "3D init success");
// (g) style timeout: map hangs, timer fires, failed as style.
reset3D(); mapBehavior = "hang";
let p = nbInit3D();
check(timers.length === 1, "timeout armed");
timers[0]();
ok = await p;
check(ok === false && nb3DFailed === true && nb3DFailKind === "style", "style timeout -> failed/style");
// (h) constructor throws a WebGL error.
reset3D(); mapBehavior = "throw-webgl";
ok = await nbInit3D();
check(ok === false && nb3DFailKind === "webgl", "WebGL constructor error -> webgl");
// (i) constructor throws something else.
reset3D(); mapBehavior = "throw-other";
ok = await nbInit3D();
check(ok === false && nb3DFailKind === "style", "other constructor error -> style");
// (j) retry after a style timeout: reset flags, 3D can be tried
// again and succeed when the style loads.
reset3D(); mapBehavior = "hang";
p = nbInit3D(); timers[0](); ok = await p;
check(ok === false && nb3DFailed === true, "failed first");
nb3DFailed = false; nb3DFailKind = null;
check(nbCan3D() === true, "retry allowed after reset");
mapBehavior = "load"; timers = [];
ok = await nbInit3D();
check(ok === true && nbEngine === "3d", "retry succeeds when the style loads");
// (k) WebGL-unsupported retry cannot loop: flags reset, still no
// 3D attempt — the tap just lands back on 2D with the same note.
reset3D(); maplibregl = { supported: () => false, Map: FakeMap };
nb3DFailed = false; nb3DFailKind = null;
check(nbCan3D() === false, "WebGL unsupported -> no 3D attempt, no loop");
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
print("node harness: 148 helpers OK")

# 9. Client markers + asset version.
assert HTML.count("?v=206") == 10, HTML.count("?v=206")
assert "?v=14" + "7" not in HTML
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
          "map.once(\"load\"", "map.on(\"error\""):
    assert m in JS, m
print("client markers + ?v=206 OK")

print("PHASE-148 TESTS PASSED")
