"""Phase-209 tests: Island Plane Landing — the 14th game (owner, Nov 27,
23:14 Dhaka: "এই গেমটি এড করবা").

The "Crazy Plane Landing" video's jet game is rebuilt in our stack
(vanilla JS + vendored Three.js r149, no React, no CDN): a teal-and-
gold jet on a tropical island runway — taxi, take off, thread three
golden rings, then land gently back on the runway. Yoke bottom-left
(drag to steer, arrow keys), throttle slider bottom-right (drag,
up/down keys). The video's look (white jet with a red tail, hands
on the controls, "Crazy Plane Landing" title) is NOT copied: teal +
gold livery, deep emerald island matching the Games section, dark-
green glass HUD, and the loop adds rings + a scored landing with a
crash on a hard or off-runway touchdown. Best score per account
(nxGet/nxSet), like Forest Drive's best — games award no points.
The loop pauses on visibilitychange; cleanup cancels rAF, removes
listeners and disposes the renderer. Plain script (run.sh runs it
directly).
"""
import os
import subprocess

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase209.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _health_version  # noqa: E402

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
GAMES = open(os.path.join(ROOT, "code/webapp/games.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
MAIN = open(os.path.join(ROOT, "code/app/main.py")).read()
c = TestClient(app)


def _extract_game_src():
    js = GAMES
    start = js.index("// --------------------------------------------- Phase 209: Island Plane Landing --")
    end = js.index("// Built last: every game above must be registered first.")
    assert 0 <= start < end, (start, end)
    src = js[start:end]
    assert 'id: "plane-landing"' in src, "plane-landing id missing"
    assert '"Island Plane Landing"' in src, "title missing"
    assert "requestAnimationFrame" in src, "rAF loop missing"
    assert "visibilitychange" in src, "hidden-tab pause missing"
    assert "renderer.dispose" in src, "renderer dispose missing"
    assert "nx_planelanding_best" in src, "per-account best missing"
    assert "pl-yoke" in src and "pl-throttle" in src, "yoke + throttle missing"
    assert "pl-map" in src and "pl-speed" in src and "pl-phase" in src, \
        "minimap/speed/phase HUD missing"
    assert "CanvasTexture" in src, "ground canvas texture missing"
    assert "TorusGeometry" in src, "rings missing"
    assert "points_balance" not in src and "award_points" not in src, \
        "games award no points"
    return src


# --- 1. Static: 14 games, the plane game, no old emoji on its face. --
assert GAMES.count("registerGame({") == 14, GAMES.count("registerGame({")
src209 = _extract_game_src()
assert 'icon: \'<svg viewBox="0 0 64 64"' in src209, "icon must be a 64x64 svg tile"
for m in ("0D9488", "F59E0B", "0C2115"):
    assert m in src209, f"icon missing scene marker {m}"
assert "Forest Drive" in GAMES and "Runner Rush" in GAMES, "older 3D games lost"
for m in ("pl-wrap", "pl-canvas", "pl-panel", "pl-phase", "pl-speed",
          "pl-map", "pl-touch", "pl-yoke", "pl-throttle", "pl-over",
          "pl-retry", "cleanup._pl", "teleport", "RINGS"):
    assert m in src209, f"plane marker lost: {m}"
# The video's title and livery are NOT copied: the def's own name and
# title are the new "Island Plane Landing" (the header comment names
# the source video only to document the differentiation).
assert 'name: "Island Plane Landing"' in src209, "def name must be the new title"
assert 'title: "Island Plane Landing"' in src209, "def title must be the new title"
assert '"Crazy Plane Landing"' not in src209.split("start(stage")[1], \
    "source title copied into the game code"
print("1. games.js: 14 games, plane-landing registered, teal/gold icon OK")

# --- 2. CSS: Phase 209 block, dark-green HUD, immersive extended. ----
assert "Phase 209 — Island Plane Landing" in CSS, "block missing"
for m in (".pl-wrap { position: relative; width: 100%; }",
          ".pl-canvas { display: block; width: 100%; height: auto;",
          ".pl-yoke { width: 112px; height: 112px;",
          ".pl-thr-track { position: relative; width: 56px; height: 148px;",
          ".pl-thr-handle { position: absolute; left: 6px; right: 6px;",
          ".pl-map { position: absolute; left: 50%;",
          ".pl-over { position: absolute; left: 50%; top: 38%;",
          ".pl-retry { margin-top: 12px;",
          "#view-game.immersive .pl-panel { display: none; }",
          "#view-game.immersive .pl-map { width: 64px; height: 64px; bottom: 80px; }"):
    assert m in CSS, f"missing CSS marker: {m}"
# The Phase 197 immersive selectors still contain the old substrings
# (test_phase197 pins them) AND now carry the plane classes.
for m in ("#view-game.immersive .fd-wrap, #view-game.immersive .rr-wrap",
          "#view-game.immersive .fd-canvas, #view-game.immersive .rr-canvas",
          "#view-game.immersive .fd-touch, #view-game.immersive .rr-touch",
          "#view-game.immersive .pl-wrap",
          "#view-game.immersive .pl-canvas",
          "#view-game.immersive .pl-touch"):
    assert m in CSS, f"immersive selector lost: {m}"
print("2. CSS: Phase 209 block, HUD + immersive OK")

# --- 3. Mascot + Nexa know the 14th game. ----------------------------
assert "14 games are built in" in JS, "mascot tip must say 14 games"
assert "Island Plane Landing" in JS, "mascot must name the plane game"
assert "13 games are built in" not in JS, "stale 13-games tip"
assert "14 games" in MAIN and "Island Plane Landing" in MAIN, \
    "Nexa must know 14 games incl. Island Plane Landing"
assert MAIN.count("Island Plane Landing") == 3, MAIN.count("Island Plane Landing")
assert "১৪টা গেম আছে" in MAIN, "Nexa BN must say 14 games"
assert "13 games" not in MAIN, "stale 13-games in Nexa knowledge"
print("3. mascot + Nexa know 14 games OK")

# --- 4. Version pins + routes + backup + health. ----------------------
assert HTML.count("?v=209") == 10, HTML.count("?v=209")
assert "?v=20" + "8" not in HTML
assert "app.js?v=209" in HTML and "games.js?v=209" in HTML
assert "style.css?v=209" in HTML
assert 'menu_url.rstrip("/") + "/?v=209"' in BOT
assert ("/?v=20" + "8") not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 191, len(paths)
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert _health_version() == 209, _health_version()
print("4. version ?v=209, routes 191, backup 55, health 209 OK")

HARNESS_PRELUDE = r'''
"use strict";
function makeCtx2d() {
  const calls = [];
  const ctx = { calls, fillStyle: "", strokeStyle: "", lineWidth: 1,
    fillRect() { calls.push("fillRect"); }, clearRect() { calls.push("clearRect"); },
    beginPath() { calls.push("beginPath"); }, closePath() { calls.push("closePath"); },
    arc() { calls.push("arc"); }, ellipse() { calls.push("ellipse"); },
    stroke() { calls.push("stroke"); }, fill() { calls.push("fill"); },
    moveTo() { calls.push("moveTo"); }, lineTo() { calls.push("lineTo"); },
    save() { calls.push("save"); }, restore() { calls.push("restore"); },
    translate() { calls.push("translate"); }, rotate() { calls.push("rotate"); },
    setLineDash() { calls.push("setLineDash"); }, fillText() { calls.push("fillText"); } };
  return ctx;
}
function makeEl(tag) {
  const el = {
    tag, children: [], hidden: false, id: "", className: "",
    textContent: "", value: "", type: "", inputMode: "",
    maxLength: 0, placeholder: "", onclick: null, parent: null,
    width: 0, height: 0, clientWidth: 0, clientHeight: 0,
    style: { setProperty(k, v) { this[k] = v; } },
    dataset: {},
    _handlers: {},
    _cls: new Set(),
    classList: { add(...c) { c.forEach(x => el._cls.add(x)); }, remove(...c) { c.forEach(x => el._cls.delete(x)); }, contains(x) { return el._cls.has(x); } },
    addEventListener(t, fn) { (el._handlers[t] = el._handlers[t] || []).push(fn); },
    removeEventListener(t, fn) { const h = el._handlers[t] || []; const i = h.indexOf(fn); if (i >= 0) h.splice(i, 1); },
    _fire(t, ev) { (el._handlers[t] || []).forEach(fn => fn(ev || {})); },
    focus() { focusedEl = el; },
    setAttribute(k, v) { el[k] = v; },
    getContext(kind) { if (kind === "2d") { el._ctx = el._ctx || makeCtx2d(); return el._ctx; } return null; },
    getBoundingClientRect() { return { top: 0, left: 0, width: el.clientWidth || 64, height: el.clientHeight || 148 }; },
    setPointerCapture() {},
    append(...kids) { for (const k of kids) { k.parent = el; el.children.push(k); } },
    appendChild(k) { k.parent = el; el.children.push(k); return k; },
    prepend(...kids) { for (let i = kids.length - 1; i >= 0; i--) { kids[i].parent = el; el.children.unshift(kids[i]); } },
    remove() { if (el.parent) { const i = el.parent.children.indexOf(el); if (i >= 0) el.parent.children.splice(i, 1); el.parent = null; } },
  };
  return el;
}
const docHandlers = {};
const document = {
  createElement: (t) => makeEl(t),
  hidden: false,
  addEventListener(t, fn) { (docHandlers[t] = docHandlers[t] || []).push(fn); },
  removeEventListener(t, fn) { const h = docHandlers[t] || []; const i = h.indexOf(fn); if (i >= 0) h.splice(i, 1); },
  _fire(t, ev) { (docHandlers[t] || []).forEach(fn => fn(ev || {})); },
};
const winHandlers = {};
const window = {
  devicePixelRatio: 1,
  WebGLRenderingContext: function () {},
  addEventListener(t, fn) { (winHandlers[t] = winHandlers[t] || []).push(fn); },
  removeEventListener(t, fn) { const h = winHandlers[t] || []; const i = h.indexOf(fn); if (i >= 0) h.splice(i, 1); },
  _fire(t, ev) { (winHandlers[t] || []).forEach(fn => fn(ev || {})); },
};
let focusedEl = null;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
function assert(c, msg) { if (!c) throw new Error("ASSERT FAILED: " + msg); }
function findByClass(el, cls, out) {
  out = out || [];
  if ((el.className || "").split(" ").includes(cls)) out.push(el);
  for (const ch of el.children) findByClass(ch, cls, out);
  return out;
}
function findBtn(el, label) {
  if (el.tag === "button" && el.textContent === label) return el;
  for (const ch of el.children) { const f = findBtn(ch, label); if (f) return f; }
  return null;
}
function visibleText(el) {
  let t = el.textContent || "";
  for (const ch of el.children) t += " " + visibleText(ch);
  return t;
}
function fireKey(t, code) { window._fire(t, { code, preventDefault() {} }); }
const _store = new Map();
const localStorage = { getItem: (k) => _store.has(k) ? _store.get(k) : null, setItem: (k, v) => _store.set(k, String(v)), removeItem: (k) => _store.delete(k) };
function nxUid() { return "anon"; }
function nxGet(k) { return localStorage.getItem(k + "_" + nxUid()); }
function nxSet(k, v) { localStorage.setItem(k + "_" + nxUid(), v); }
const GameRegistry = [];
function registerGame(def) { GameRegistry.push(def); }
let rafId = 0; const rafQueue = new Map();
function requestAnimationFrame(cb) { const id = ++rafId; rafQueue.set(id, cb); return id; }
function cancelAnimationFrame(id) { rafQueue.delete(id); }
let simTime = 0;
function stepFrames(n, dtMs) { for (let i = 0; i < n; i++) { simTime += dtMs; const cbs = [...rafQueue.values()]; rafQueue.clear(); cbs.forEach(cb => cb(simTime)); } }
function mkVec3(x, y, z) {
  return { x: x || 0, y: y || 0, z: z || 0,
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; },
    setScalar(s) { this.x = s; this.y = s; this.z = s; return this; },
    lerp(t, a) { this.x += (t.x - this.x) * a; this.y += (t.y - this.y) * a; this.z += (t.z - this.z) * a; return this; },
    copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; } };
}
function mkNode() {
  const n = { position: mkVec3(), rotation: mkVec3(), scale: mkVec3(1, 1, 1),
    children: [], parent: null,
    add(...objs) { for (const o of objs) { o.parent = n; n.children.push(o); } return n; },
    remove(...objs) { for (const o of objs) { const i = n.children.indexOf(o); if (i >= 0) n.children.splice(i, 1); } return n; },
    traverse(fn) { fn(n); for (const c of n.children) c.traverse(fn); } };
  return n;
}
const created = { meshes: [], geometries: [], materials: [], renderers: [], textures: [], renderCalls: 0, disposeCalls: 0 };
function mkGeo(kind, args) { const g = { kind, args, disposed: false, dispose() { g.disposed = true; } }; created.geometries.push(g); return g; }
function mkMat(kind, params) { const m = { kind, params: params || {}, map: (params && params.map) || null, disposed: false, color: { set(c) { m._color = c; } }, dispose() { m.disposed = true; } }; created.materials.push(m); return m; }
let THREE = {
  sRGBEncoding: "sRGB",
  Color: function (c) { this.c = c; },
  Fog: function (c, n, f) { this.c = c; this.near = n; this.far = f; },
  Scene: function () { const s = mkNode(); s.background = null; s.fog = null; return s; },
  PerspectiveCamera: function (fov, aspect, near, far) {
    const c = mkNode();
    c.fov = fov; c.aspect = aspect; c.near = near; c.far = far; c.lookAtCalls = 0;
    c.lookAt = function () { c.lookAtCalls++; };
    c.updateProjectionMatrix = function () {};
    return c;
  },
  WebGLRenderer: function (opts) {
    const r = { domElement: opts.canvas, renderCalls: 0, disposed: false,
      setPixelRatio() {}, setSize() {},
      render() { r.renderCalls++; created.renderCalls++; },
      dispose() { r.disposed = true; created.disposeCalls++; } };
    created.renderers.push(r);
    return r;
  },
  HemisphereLight: function () { return mkNode(); },
  DirectionalLight: function () { return mkNode(); },
  Mesh: function (geo, mat) { const m = mkNode(); m.geometry = geo; m.material = mat; created.meshes.push(m); return m; },
  Group: function () { return mkNode(); },
  BoxGeometry: function (...a) { return mkGeo("box", a); },
  CylinderGeometry: function (...a) { return mkGeo("cylinder", a); },
  ConeGeometry: function (...a) { return mkGeo("cone", a); },
  IcosahedronGeometry: function (...a) { return mkGeo("icosahedron", a); },
  PlaneGeometry: function (...a) { return mkGeo("plane", a); },
  CircleGeometry: function (...a) { return mkGeo("circle", a); },
  TorusGeometry: function (...a) { return mkGeo("torus", a); },
  SphereGeometry: function (...a) { return mkGeo("sphere", a); },
  MeshLambertMaterial: function (p) { return mkMat("lambert", p); },
  MeshStandardMaterial: function (p) { return mkMat("standard", p); },
  CanvasTexture: function (cv) { const t = { canvas: cv, encoding: null, disposed: false, dispose() { t.disposed = true; } }; created.textures.push(t); return t; },
  Vector3: function (x, y, z) { return mkVec3(x, y, z); },
};
'''

HARNESS_MAIN = r'''
(async () => {
  const def = GameRegistry[0];
  assert(def, "plane-landing registered");
  assert(def.id === "plane-landing", "id plane-landing, got " + def.id);
  assert(def.icon.includes("<svg") && def.icon.includes("0D9488")
      && def.icon.includes("F59E0B") && def.icon.includes("0C2115"), "teal jet icon");
  assert(def.name === "Island Plane Landing", "name");
  assert(def.title === "Island Plane Landing", "title");
  assert(def.desc.includes("teal jet") && def.desc.includes("centreline"), "desc names the jet + landing");
  assert(def.help.includes("yoke") && def.help.includes("Throttle"), "help names yoke + throttle");
  const stage = makeEl("div");
  let scoreText = "";
  const cleanup = def.start(stage, (s) => { scoreText = s; });
  assert(typeof cleanup === "function", "start returns cleanup");
  assert(cleanup._pl, "test hook present");
  assert(findByClass(stage, "pl-wrap").length === 1, "pl-wrap present");
  assert(findByClass(stage, "pl-canvas").length === 1, "game canvas present");
  assert(findByClass(stage, "pl-panel").length === 1, "controls panel present");
  assert(findByClass(stage, "pl-phase").length === 1, "phase pill present");
  assert(findByClass(stage, "pl-speed").length === 1, "speed display present");
  assert(findByClass(stage, "pl-map").length === 1, "minimap present");
  assert(findByClass(stage, "pl-touch").length === 1, "touch controls present");
  assert(findByClass(stage, "pl-yoke").length === 1, "yoke present");
  assert(findByClass(stage, "pl-throttle").length === 1, "throttle present");
  assert(findByClass(stage, "pl-over").length === 1, "overlay present");
  assert(findBtn(stage, "Retry"), "Retry button present");
  assert(created.renderers.length === 1, "one renderer created");
  assert(created.meshes.length >= 240, "scene has 240+ meshes, got " + created.meshes.length);
  assert(created.geometries.length >= 12, "geometries built, got " + created.geometries.length);
  assert(created.textures.length === 1, "ground canvas texture created");
  assert(cleanup._pl.palms().length === 42, "42 palms placed");
  assert(cleanup._pl.rings().length === 3, "3 rings placed");
  assert(scoreText === "✈️ Score: 0 · Best: 0", "initial score, got " + scoreText);
  const speedB = findByClass(stage, "pl-speed")[0].children[0];
  assert(speedB.textContent === "0", "speed starts at 0");
  stepFrames(10, 16);
  assert(created.renderCalls >= 10, "frames render, got " + created.renderCalls);
  fireKey("keydown", "ArrowUp");
  stepFrames(400, 16);
  let st = cleanup._pl.state();
  assert(st.throttle > 0.9, "throttle reaches full, got " + st.throttle);
  assert(st.airborne, "jet takes off, airborne=" + st.airborne + " speed=" + st.speed + " y=" + st.y);
  assert(st.y > 0, "jet climbs, y=" + st.y);
  assert(st.phase === "FLY", "phase FLY, got " + st.phase);
  assert(+speedB.textContent > 0, "speed HUD updates, got " + speedB.textContent);
  fireKey("keyup", "ArrowUp");
  const h0 = st.heading;
  fireKey("keydown", "ArrowLeft");
  stepFrames(30, 16);
  st = cleanup._pl.state();
  assert(st.heading !== h0, "steering changes heading");
  fireKey("keyup", "ArrowLeft");
  const yokeEl = findByClass(stage, "pl-yoke")[0];
  const h1 = cleanup._pl.state().heading;
  yokeEl._fire("pointerdown", { clientX: 100, preventDefault() {} });
  yokeEl._fire("pointermove", { clientX: 30 });
  stepFrames(20, 16);
  assert(cleanup._pl.state().heading !== h1, "yoke drag steers");
  yokeEl._fire("pointerup", {});
  const r1 = cleanup._pl.rings()[0];
  cleanup._pl.teleport(r1.x, r1.y, r1.z, Math.PI);
  stepFrames(3, 16);
  st = cleanup._pl.state();
  assert(st.rings === 1, "ring 1 collected, got " + st.rings);
  assert(st.score === 100, "ring scores 100, got " + st.score);
  assert(st.best === 100, "best score recorded");
  const tr = cleanup._pl.palms()[0];
  cleanup._pl.teleport(tr.x, 2, tr.z, 0);
  stepFrames(3, 16);
  st = cleanup._pl.state();
  assert(st.phase === "CRASH", "palm crash, phase " + st.phase);
  assert(visibleText(stage).includes("palm tree"), "crash names the palm");
  const retry = findBtn(stage, "Retry");
  retry.onclick();
  st = cleanup._pl.state();
  assert(st.phase === "TAXI" && st.score === 0 && st.rings === 0, "retry resets the run");
  assert(st.best === 100, "best survives retry");
  cleanup._pl.teleport(0, 18, -60, 0);
  cleanup._pl.setThrottle(0.3);
  stepFrames(500, 16);
  st = cleanup._pl.state();
  assert(st.phase === "ROLLOUT" || st.phase === "DONE", "gentle touchdown rolls out, phase " + st.phase + " y=" + st.y + " vy=" + st.vy);
  assert(st.score > 100, "landing scores, got " + st.score);
  stepFrames(200, 16);
  st = cleanup._pl.state();
  assert(st.phase === "DONE", "run completes, phase " + st.phase);
  assert(visibleText(stage).includes("Landed!"), "overlay celebrates the landing");
  findBtn(stage, "Retry").onclick();
  cleanup._pl.teleport(0, 18, -60, 0);
  cleanup._pl.setThrottle(0);
  stepFrames(400, 16);
  st = cleanup._pl.state();
  assert(st.phase === "CRASH", "hard landing crashes, phase " + st.phase);
  assert(visibleText(stage).includes("Too hard"), "crash names the hard touchdown");
  const mapCv = findByClass(stage, "pl-map")[0];
  const mcalls = mapCv._ctx.calls;
  assert(mcalls.includes("arc"), "minimap draws circles");
  assert(mcalls.filter((c) => c === "fillRect").length >= 10, "minimap draws runway + palms");
  const rc = created.renderCalls;
  document.hidden = true;
  document._fire("visibilitychange", {});
  stepFrames(10, 16);
  assert(created.renderCalls === rc, "hidden tab pauses rendering");
  document.hidden = false;
  document._fire("visibilitychange", {});
  stepFrames(5, 16);
  assert(created.renderCalls > rc, "visible tab resumes rendering");
  cleanup();
  assert(created.disposeCalls === 1, "renderer disposed on exit");
  assert((winHandlers["keydown"] || []).length === 0, "keyboard listeners removed");
  assert((docHandlers["visibilitychange"] || []).length === 0, "visibility listener removed");
  const rc2 = created.renderCalls;
  stepFrames(5, 16);
  assert(created.renderCalls === rc2, "no frames after cleanup");
  const savedTHREE = THREE;
  THREE = undefined;
  const stage2 = makeEl("div");
  const cleanup2 = def.start(stage2, () => {});
  assert(typeof cleanup2 === "function", "fallback returns cleanup");
  assert(visibleText(stage2).includes("3D is not available"), "fallback explains no-3D");
  THREE = savedTHREE;
  console.log("HARNESS OK (plane-landing: scene, takeoff, steer, yoke, rings, palm crash, landing, hard-landing crash, retry, minimap, pause, cleanup, no-WebGL)");
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_node_harness():
    src = _extract_game_src()
    harness = HARNESS_PRELUDE + src + HARNESS_MAIN
    path = "/tmp/t209_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    assert "HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("node harness OK (plane-landing: scene, takeoff, steer, yoke, "
          "rings, palm crash, landing, hard-landing crash, retry, "
          "minimap, pause, cleanup, no-WebGL)")


# --- 5. JS still parses + the Node harness proves the game. -----------
for name in ("app.js", "games.js"):
    r = subprocess.run(["node", "--check",
                        os.path.join(ROOT, "code/webapp", name)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("5. node --check OK (games.js + app.js parse)")
_run_node_harness()

# --- 6. Served assets: version + markers + neighbours. ----------------
html = c.get("/webapp/").text
assert html.count("?v=209") == 10, html.count("?v=209")
assert "?v=20" + "8" not in html
assert "app.js?v=209" in html and "games.js?v=209" in html
assert "style.css?v=209" in html and "three.min.js?v=209" in html
served_games = c.get("/webapp/games.js").text
for marker in ("plane-landing", "Island Plane Landing", "pl-yoke",
               "pl-throttle", "pl-map", "pl-speed", "pl-phase",
               "forest-drive", "runner-rush", "renderer.dispose",
               "requestAnimationFrame"):
    assert marker in served_games, marker
served_js = c.get("/webapp/app.js").text
assert "14 games are built in" in served_js
css = c.get("/webapp/style.css").text
for marker in ("Phase 209 — Island Plane Landing", ".pl-wrap",
               ".pl-yoke", ".pl-thr-handle", ".pl-over",
               "#view-game.immersive .pl-wrap"):
    assert marker in css, marker
print("6. served assets ?v=209 + markers OK")

print("PHASE 209 OK (Island Plane Landing)")
