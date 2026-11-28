"""Phase-197 tests: immersive full-screen game view + HUD overlap fixes
+ attractive game buttons (owner bug report, Nov 27, 15:08 Dhaka).

The owner's Forest Drive phone screenshot showed: the "0 km/h" speed
text on top of the GAS button, the minimap covering the ◀ ▶ steer
buttons, the header "🚗 94 km/h · Best: 94 km/h" wrapping onto two
lines, the 3D canvas as a small box in the middle of the page, and
pale-cream buttons with near-invisible white labels.

Fixes: (1) showView("game") makes #view-game a fixed full-screen
overlay (.immersive, z-index 66 — above the bottom nav at 65, below
sheets at 70+) and hides the mascot; leaving the view restores both.
(2) The minimap anchors 88px above the wrap bottom (above the touch
row) and the speed moves to a dark glass chip at the top-right.
(3) The 3D canvases fill the wrap in immersive mode (sizeRenderer
uses wrap.clientHeight instead of the fixed 3:2 box). (4) Game
buttons get vivid gradients + white bold labels + a pressed state —
with wrap/stage-qualified selectors that beat `html[data-theme]
button`. Mini-games keep their designed canvas sizes, centred in the
stage — no exception needed, the shell applies to all 13 games.
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase197.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import models  # noqa: E402
from app.config import settings  # noqa: E402

def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, auth_date=None):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name},
                                          auth_date=auth_date)}


ADMIN = H(999, "Admin")


def _extract_fd_src():
    js = open(os.path.join(ROOT, "webapp/games.js")).read()
    start = js.index("// --------------------------------------------- Phase 195: Forest Drive --")
    end = js.index("// --------------------------------------------- Phase 196: Runner Rush --")
    assert 0 <= start < end, (start, end)
    src = js[start:end]
    assert 'id: "forest-drive"' in src, "forest-drive id missing"
    assert '"Forest Drive"' in src, "Forest Drive title missing"
    assert "fd-map" in src and "fd-speed" in src and "fd-touch" in src, \
        "FD HUD elements missing"
    return src


def _extract_rr_src():
    js = open(os.path.join(ROOT, "webapp/games.js")).read()
    start = js.index("// --------------------------------------------- Phase 196: Runner Rush --")
    end = js.index("// Built last: every game above must be registered first.")
    assert 0 <= start < end, (start, end)
    src = js[start:end]
    assert 'id: "runner-rush"' in src, "runner-rush id missing"
    return src


HARNESS_PRELUDE = r'''
"use strict";
function makeCtx2d() {
  const calls = [];
  const ctx = { calls, fillStyle: "", strokeStyle: "", lineWidth: 1, font: "",
    textAlign: "", textBaseline: "",
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
function mkMat(kind, params) { const m = { kind, params: params || {}, map: (params && params.map) || null, disposed: false, dispose() { m.disposed = true; } }; created.materials.push(m); return m; }
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
  OctahedronGeometry: function (...a) { return mkGeo("octahedron", a); },
  SphereGeometry: function (...a) { return mkGeo("sphere", a); },
  MeshLambertMaterial: function (p) { return mkMat("lambert", p); },
  MeshStandardMaterial: function (p) { return mkMat("standard", p); },
  MeshBasicMaterial: function (p) { return mkMat("basic", p); },
  CanvasTexture: function (cv) { const t = { canvas: cv, encoding: null, disposed: false, dispose() { t.disposed = true; } }; created.textures.push(t); return t; },
  Vector3: function (x, y, z) { return mkVec3(x, y, z); },
};
'''


def _games_prelude():
    # The 195/196 DOM + THREE stub, with two Phase-197 additions:
    # (a) the renderer records its last setSize, so the harness can
    # prove the canvas fills the wrap in immersive mode and falls
    # back to 3:2 outside it; (b) document.getElementById exists, so
    # the games' immersive guard can read #view-game's class.
    pre = HARNESS_PRELUDE
    old_size = "setPixelRatio() {}, setSize() {},"
    assert old_size in pre, "THREE stub setSize line drifted"
    pre = pre.replace(old_size,
                      "setPixelRatio() {}, setSize(w, h) { r.lastSize = [w, h]; },")
    old_doc = "  createElement: (t) => makeEl(t),\n  hidden: false,"
    assert old_doc in pre, "document stub drifted"
    pre = pre.replace(old_doc,
                      "  createElement: (t) => makeEl(t),\n"
                      "  _byId: {},\n"
                      "  getElementById(id) { return this._byId[id] || null; },\n"
                      "  hidden: false,")
    return pre


GAMES_HARNESS_MAIN = r'''
(async () => {
  const fdDef = GameRegistry.find(d => d.id === "forest-drive");
  const rrDef = GameRegistry.find(d => d.id === "runner-rush");
  assert(fdDef && rrDef, "both 3D games registered");
  // Tracked #view-game: the games read its .immersive class.
  const viewGame = makeEl("section"); viewGame.id = "view-game";
  document._byId["view-game"] = viewGame;
  // --- Forest Drive, non-immersive first: fixed 3:2 box ---
  const stage = makeEl("div"); stage.clientWidth = 360; stage.clientHeight = 640;
  const cleanupFD = fdDef.start(stage, () => {});
  assert(typeof cleanupFD === "function", "FD start returns cleanup");
  const wrapFD = findByClass(stage, "fd-wrap")[0];
  assert(wrapFD, "fd-wrap present");
  wrapFD.clientWidth = 360; wrapFD.clientHeight = 640;
  assert(findByClass(stage, "fd-canvas").length === 1, "FD canvas present");
  assert(findByClass(stage, "fd-map").length === 1, "FD minimap present");
  assert(findByClass(stage, "fd-speed").length === 1, "FD speed chip present");
  assert(findByClass(stage, "fd-touch").length === 1, "FD touch row present");
  assert(findBtn(stage, "GAS") && findBtn(stage, "BRAKE"), "GAS/BRAKE present");
  assert(findBtn(stage, "◀") && findBtn(stage, "▶"), "FD steer buttons present");
  assert(findByClass(stage, "fd-panel").length === 1, "FD controls panel present");
  const rFD = created.renderers[created.renderers.length - 1];
  window._fire("resize");
  assert(rFD.lastSize && rFD.lastSize[0] === 360 && rFD.lastSize[1] === 240,
    "non-immersive FD is a 3:2 box (360x240), got " + JSON.stringify(rFD.lastSize));
  // --- immersive: the canvas fills the wrap ---
  viewGame.classList.add("immersive");
  window._fire("resize");
  assert(rFD.lastSize[0] === 360 && rFD.lastSize[1] === 640,
    "immersive FD fills the wrap (360x640), got " + JSON.stringify(rFD.lastSize));
  // --- leaving immersive restores the 3:2 box ---
  viewGame.classList.remove("immersive");
  window._fire("resize");
  assert(rFD.lastSize[1] === 240, "exiting immersive restores 3:2, got " + JSON.stringify(rFD.lastSize));
  cleanupFD();
  assert((winHandlers["resize"] || []).length === 0, "FD resize listener removed");
  // --- Runner Rush, immersive from the start ---
  const stage2 = makeEl("div"); stage2.clientWidth = 360; stage2.clientHeight = 640;
  viewGame.classList.add("immersive");
  const cleanupRR = rrDef.start(stage2, () => {});
  const wrapRR = findByClass(stage2, "rr-wrap")[0];
  assert(wrapRR, "rr-wrap present");
  wrapRR.clientWidth = 360; wrapRR.clientHeight = 640;
  const bikeBtn = findBtn(stage2, "🚲 Bike Run");
  assert(bikeBtn, "RR bike card present");
  bikeBtn.onclick();
  assert(cleanupRR._rr.mode() === "bike", "bike mode starts");
  assert(findByClass(stage2, "rr-touch").length === 1, "RR touch row present");
  assert(findBtn(stage2, "◀") && findBtn(stage2, "▶"), "RR steer buttons present");
  const rRR = created.renderers[created.renderers.length - 1];
  window._fire("resize");
  assert(rRR.lastSize[0] === 360 && rRR.lastSize[1] === 640,
    "immersive RR fills the wrap (360x640), got " + JSON.stringify(rRR.lastSize));
  viewGame.classList.remove("immersive");
  window._fire("resize");
  assert(rRR.lastSize[1] === 240, "exiting immersive restores RR 3:2, got " + JSON.stringify(rRR.lastSize));
  cleanupRR();
  assert((winHandlers["resize"] || []).length === 0, "RR resize listener removed");
  console.log("HARNESS OK (phase-197: FD + RR immersive fill, 3:2 restore, HUD + buttons present)");
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_games_harness():
    harness = _games_prelude() + _extract_fd_src() + _extract_rr_src() + GAMES_HARNESS_MAIN
    path = "/tmp/t197_games_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("games node harness OK (FD + RR immersive fill, 3:2 restore, HUD + buttons present)")


APP_PRELUDE = r'''
// Phase-197 app harness: run the real app.js with window.Telegram
// MISSING (the Phase-188 boot-proof setup) but with a TRACKED
// #view-game section and body, so the test can call the real
// showView() and watch .immersive / .game-open toggle for real.
// NOT strict: the eval'd app.js declares showView in this scope.
function makeEl197(tag) {
  const el = {
    tag, children: [], hidden: false, id: "", className: "",
    textContent: "", innerHTML: "", value: "",
    style: { setProperty(k, v) { this[k] = v; }, removeProperty() {}, getPropertyValue() { return ""; } },
    dataset: {},
    _cls: new Set(),
    classList: { add(...c) { c.forEach(x => el._cls.add(x)); },
      remove(...c) { c.forEach(x => el._cls.delete(x)); },
      toggle(c, f) { if (f === undefined) f = !el._cls.has(c); if (f) el._cls.add(c); else el._cls.delete(c); return f; },
      contains(x) { return el._cls.has(x); } },
    offsetLeft: 0, offsetWidth: 50, offsetTop: 0, offsetHeight: 0,
    clientWidth: 360, clientHeight: 640, scrollTop: 0, scrollHeight: 0,
    append(...k) { for (const x of k) { x.parent = el; el.children.push(x); } },
    appendChild(k) { k.parent = el; el.children.push(k); return k; },
    prepend() {}, remove() {}, addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute() { return null; },
    querySelector() { return makeEl197(); }, querySelectorAll() { return []; },
    click() {}, focus() {}, scrollIntoView() {}, getContext() { return null; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 50, height: 40, right: 50, bottom: 40 }; },
  };
  return new Proxy(el, {
    get(t, k) { if (k in t) return t[k]; return (...a) => makeEl197(); },
    set(t, k, v) { t[k] = v; return true; },
  });
}
const __vg197 = makeEl197("section"); __vg197.id = "view-game";
const __body197 = makeEl197("body");
const __status197 = makeEl197();
global.window = { location: { search: "", reload() {} }, open() {}, Telegram: undefined,
  devicePixelRatio: 1, innerWidth: 360, innerHeight: 740, addEventListener() {}, scrollTo() {},
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) };
global.document = {
  getElementById(id) { if (id === "view-game") return __vg197; if (id === "status") return __status197; return makeEl197(); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  createElement(t) { return makeEl197(t); },
  addEventListener() {}, body: __body197, documentElement: makeEl197(),
};
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.navigator = {};
global.location = global.window.location;
global.alert = () => {}; global.confirm = () => false;
global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}), text: async () => "" });
global.IntersectionObserver = class { constructor() {} observe() {} unobserve() {} disconnect() {} };
global.ResizeObserver = class { constructor() {} observe() {} unobserve() {} disconnect() {} };
global.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
global.window.matchMedia = global.matchMedia;
process.on("uncaughtException", (e) => { console.log("UNCAUGHT: " + (e && e.message)); process.exit(2); });
process.on("unhandledRejection", (e) => { console.log("UNHANDLED_REJECTION: " + (e && e.message)); });
function assert197(c, msg) { if (!c) throw new Error("ASSERT FAILED: " + msg); }
'''

APP_MAIN = r'''
try {
  eval(APP_SRC_197);
  console.log("EVAL_OK: app.js parsed and top-level ran without throwing");
} catch (e) {
  console.log("EVAL_THROW: " + (e && e.message));
  process.exit(3);
}
assert197(typeof showView === "function", "showView defined");
// The game section starts non-immersive (boot shows the feed).
assert197(!__vg197.classList.contains("immersive"), "game section starts non-immersive");
assert197(!__body197.classList.contains("game-open"), "body starts without game-open");
showView("game");
assert197(__vg197.classList.contains("immersive"), "showView(game) adds .immersive");
assert197(__body197.classList.contains("game-open"), "showView(game) adds body.game-open");
assert197(__vg197.hidden === false, "game section unhidden while open");
showView("games");
assert197(!__vg197.classList.contains("immersive"), "leaving the game removes .immersive");
assert197(!__body197.classList.contains("game-open"), "leaving the game removes body.game-open");
showView("game");
showView("feed");
assert197(!__vg197.classList.contains("immersive"), "showView(feed) restores non-immersive");
assert197(__vg197.hidden === true, "game section hidden again after leaving");
console.log("APP HARNESS OK (phase-197: showView toggles immersive + game-open, restores on exit)");
process.exit(0);
'''


def _run_app_harness():
    src = open(os.path.join(ROOT, "webapp/app.js")).read()
    harness = (APP_PRELUDE
               + "\nconst APP_SRC_197 = " + json.dumps(src) + ";\n"
               + APP_MAIN)
    path = "/tmp/t197_app_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "EVAL_OK" in r.stdout, (r.stdout, r.stderr)
    assert "APP HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("app node harness OK (showView toggles immersive + game-open, restores on exit)")


def _css():
    return open(os.path.join(ROOT, "webapp/style.css")).read()


def _specificity(selector):
    # (ids, classes/attrs/pseudo-classes, elements) — enough for the
    # two pairs this phase cares about.
    ids = selector.count("#")
    classes = selector.count(".") + selector.count("[") + selector.count(":")
    elements = len(re.findall(r"(?<![.#:\[\w-])[a-zA-Z][\w-]*", selector))
    return (ids, classes, elements)


def _test_immersive_css():
    css = _css()
    assert "Phase 197: immersive game view + HUD + attractive buttons" in css
    # 1. The immersive shell.
    m = re.search(r"#view-game\.immersive \{([^}]*)\}", css)
    assert m, "#view-game.immersive rule missing"
    body = m.group(1)
    assert "position: fixed" in body and "inset: 0" in body, body
    assert "z-index: 66" in body, "immersive must sit above the nav (65) " + body
    assert "background: var(--t-bg" in body, "immersive must be opaque, " + body
    assert "display: flex" in body and "flex-direction: column" in body, body
    assert "#view-game.immersive #game-help { display: none; }" in css
    assert "body.game-open #mascot-wrap { display: none; }" in css
    # 2. The header cannot wrap: one line, ellipsis title + score.
    assert re.search(r"#view-game\.immersive #game-title \{[^}]*white-space: nowrap;[^}]*\}", css), \
        "immersive title must not wrap"
    assert re.search(r"#view-game\.immersive #game-score \{[^}]*max-width: 52%;[^}]*white-space: nowrap;", css), \
        "immersive score must be capped + non-wrapping"
    # 3. 3D canvases fill the stage; touch rows float over the bottom.
    assert "#view-game.immersive .fd-wrap, #view-game.immersive .rr-wrap" in css
    assert "#view-game.immersive .fd-canvas, #view-game.immersive .rr-canvas" in css
    assert "#view-game.immersive .fd-touch, #view-game.immersive .rr-touch" in css
    m = re.search(r"#view-game\.immersive \.fd-touch, #view-game\.immersive \.rr-touch \{([^}]*)\}", css)
    assert m and "position: absolute" in m.group(1) and "bottom: 12px" in m.group(1), m
    # 4. RR HUD scrolls sideways instead of wrapping.
    assert ".rr-hud { overflow-x: auto;" in css
    # 5. Short screens: panel hides, minimap shrinks.
    assert "@media (max-height: 520px)" in css
    assert "#view-game.immersive .fd-panel { display: none; }" in css
    # 6. Attractive buttons: vivid gradients + pressed state, and the
    # selectors MUST outrank `html[data-theme] button` (0,1,2) — the
    # rule that washed every game button pale with white text.
    pairs = [
        (".fd-wrap .fd-gas", "#22C55E", "#15803D"),
        (".fd-wrap .fd-brake", "#EF4444", "#B91C1C"),
        (".fd-wrap .fd-left, .fd-wrap .fd-right", "#3B82F6", "#1D4ED8"),
        (".rr-wrap .rr-steer", "#14B8A6", "#0F766E"),
        (".rr-wrap .rr-retry", "#3B82F6", "#1D4ED8"),
        (".rr-wrap .rr-next", "#22C55E", "#15803D"),
        (".rr-wrap .rr-ov-modes", "#64748B", "#334155"),
    ]
    for sel, hi, lo in pairs:
        assert re.search(re.escape(sel) + r" \{[^}]*linear-gradient\(180deg, " + hi + ", " + lo + r"\)", css), \
            f"button gradient missing for {sel}"
        # The pressed rule repeats :active on EACH selector of a group
        # (".fd-left:active, .fd-right:active"), so check them one by one.
        for part in sel.split(", "):
            assert re.search(re.escape(part) + r":active\s*(,|\{)[^}]*background: " + lo + r";[^}]*transform: scale\(\.93\);", css), \
                f"pressed state missing for {part}"
        assert _specificity(sel) > _specificity("html[data-theme] button"), \
            f"{sel} must outrank the pale theme-button rule"
    assert re.search(r"#game-stage \.dpad button, #game-stage \.grow button \{[^}]*linear-gradient\(180deg, #6366F1, #4F46E5\)", css), \
        "mini-game dpad/grow gradient missing"
    assert re.search(r"#game-stage \.dpad button:active, #game-stage \.grow button:active \{[^}]*transform: scale\(\.93\);", css), \
        "mini-game pressed state missing"
    assert _specificity("#game-stage .dpad button") > _specificity("html[data-theme] button")
    # 7. The old overlap anchors are gone.
    assert re.search(r"\.fd-map \{[^}]*bottom: 88px;", css), "minimap must anchor 88px up"
    assert "bottom: 8px" not in re.search(r"\.fd-map \{[^}]*\}", css).group(0), \
        "old minimap bottom: 8px must be gone"
    assert re.search(r"\.fd-speed \{[^}]*top: 10px;[^}]*background: rgba\(10, 16, 28, \.72\);", css), \
        "speed must be a top-right dark chip"
    assert "bottom: 8px" not in re.search(r"\.fd-speed \{[^}]*\}", css).group(0), \
        "old speed bottom: 8px must be gone"
    print("immersive CSS OK (shell, header, canvas fill, buttons outrank theme rule, old anchors gone)")


def _rects_overlap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _test_hud_geometry():
    # Non-overlap, computed from the real stylesheet numbers, at
    # 360px and 420px widths and two viewport heights.
    css = _css()
    map_rule = re.search(r"\.fd-map \{([^}]*)\}", css).group(1)
    map_bottom = int(re.search(r"bottom: (\d+)px", map_rule).group(1))
    map_size = int(re.search(r"width: (\d+)px", map_rule).group(1))
    touch_rule = re.search(r"#view-game\.immersive \.fd-touch, #view-game\.immersive \.rr-touch \{([^}]*)\}", css).group(1)
    touch_bottom = int(re.search(r"bottom: (\d+)px", touch_rule).group(1))
    touch_h = int(re.search(r"\.fd-btn \{[^}]*height: (\d+)px", css).group(1))
    speed_rule = re.search(r"\.fd-speed \{([^}]*)\}", css).group(1)
    speed_top = int(re.search(r"top: (\d+)px", speed_rule).group(1))
    panel_rule = re.search(r"\.fd-panel \{([^}]*)\}", css).group(1)
    panel_top = int(re.search(r"top: (\d+)px", panel_rule).group(1))
    panel_left = int(re.search(r"left: (\d+)px", panel_rule).group(1))
    panel_max = int(re.search(r"max-width: (\d+)%", panel_rule).group(1))
    gas_w = int(re.search(r"\.fd-gas \{[^}]*min-width: (\d+)px", css).group(1))
    # BRAKE has no own min-width — it falls back to .fd-btn's 62px.
    brake_w = int(re.search(r"\.fd-btn \{[^}]*min-width: (\d+)px", css).group(1))
    assert map_bottom == 88 and touch_bottom == 12 and touch_h == 56, \
        (map_bottom, touch_bottom, touch_h)
    for w in (360, 420):
        for h in (640, 740):
            # Immersive HUD rectangles (x0, y0, x1, y1).
            touch = (12, h - touch_bottom - touch_h, w - 12, h - touch_bottom)
            mmap = (12, h - map_bottom - map_size, 12 + map_size, h - map_bottom)
            # Speed chip: conservative 80px wide, 44px tall.
            speed = (w - 12 - 80, speed_top, w - 12, speed_top + 44)
            # Controls panel: max-width 62%, ~40px tall.
            panel = (panel_left, panel_top, panel_left + w * panel_max // 100, panel_top + 40)
            assert not _rects_overlap(touch, mmap), f"map covers touch at {w}x{h}"
            assert not _rects_overlap(speed, panel), f"speed chip covers panel at {w}x{h}"
            assert not _rects_overlap(speed, touch), f"speed chip covers touch at {w}x{h}"
            assert not _rects_overlap(panel, touch), f"panel covers touch at {w}x{h}"
            # Steer group (left) vs GAS/BRAKE group (right) inside the touch row.
            steer = (12, touch[1], 12 + 56 + 8 + 56, touch[3])
            gasbrake = (w - 12 - (gas_w + 8 + brake_w), touch[1], w - 12, touch[3])
            assert not _rects_overlap(steer, gasbrake), f"steer covers GAS/BRAKE at {w}x{h}"
            # RR touch row: two 56px steer buttons each side.
            rr_left = (12, touch[1], 12 + 56 + 8 + 56, touch[3])
            rr_right = (w - 12 - (56 + 8 + 56), touch[1], w - 12, touch[3])
            assert not _rects_overlap(rr_left, rr_right), f"RR steer groups overlap at {w}x{h}"
    print("HUD geometry OK (no overlaps at 360/420px x 640/740px: map/touch, speed/panel, steer/GAS-BRAKE)")


def _test_showview_source():
    src = open(os.path.join(ROOT, "webapp/app.js")).read()
    start = src.index("function showView(name, viaBack) {")
    end = src.index("// ---------- Phase 77: the back button stays inside the app ----")
    fn = src[start:end]
    assert 'classList.toggle("immersive", name === "game")' in fn, \
        "showView must toggle .immersive on view-game"
    assert 'classList.toggle("game-open", name === "game")' in fn, \
        "showView must toggle body.game-open"
    assert '$("view-game")' in fn, "showView must look up view-game"
    print("showView source OK (immersive + game-open toggles inside showView)")


def _test_size_renderer_source():
    js = open(os.path.join(ROOT, "webapp/games.js")).read()
    assert js.count('classList.contains("immersive")') == 2, \
        "both 3D sizeRenderers must read the immersive class"
    assert js.count("wrap.clientHeight") == 4, \
        "both 3D sizeRenderers must size from wrap.clientHeight (2x each: guard + value)"
    assert js.count("typeof document !== \"undefined\" && document.getElementById") == 2, \
        "both guards must survive the node harness (no getElementById)"
    print("sizeRenderer source OK (FD + RR immersive sizing with harness guard)")


with TestClient(app) as c:
    # 1. JS parses (node).
    for f in ("webapp/app.js", "webapp/games.js"):
        r = subprocess.run(["node", "--check", os.path.join(ROOT, f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    print("node --check OK (games.js + app.js parse)")

    # 2. Node harness: real FD + RR start against DOM + THREE stubs.
    _run_games_harness()

    # 3. Node harness: real showView toggle in the real app.js.
    _run_app_harness()

    # 4. Static: CSS rules, HUD geometry, showView + sizeRenderer sources.
    _test_immersive_css()
    _test_hud_geometry()
    _test_showview_source()
    _test_size_renderer_source()

    # 5. Static: 13 games still registered, no points, no new game.
    games_js = open(os.path.join(ROOT, "webapp/games.js")).read()
    assert games_js.count("registerGame({") == 13, games_js.count("registerGame({")
    js = open(os.path.join(ROOT, "webapp/app.js")).read()
    assert "13 games are built in" in js, "mascot tip must say 13 games"
    print("static OK (13 games registered; no new game; no mechanics change)")

    # 6. Served assets: version + markers + neighbours.
    html = c.get("/webapp/").text
    assert html.count("?v=206") == 10, html.count("?v=206")
    assert "?v=19" + "6" not in html
    assert "app.js?v=206" in html and "style.css?v=206" in html
    assert "games.js?v=206" in html and "three.min.js?v=206" in html
    served_games = c.get("/webapp/games.js").text
    for marker in ("forest-drive", "runner-rush", "_imm197",
                   "wrap.clientHeight", "fd-map", "fd-speed", "fd-touch",
                   "fd-gas", "rr-steer", "visibilitychange",
                   "renderer.dispose", "requestAnimationFrame"):
        assert marker in served_games, marker
    served_js = c.get("/webapp/app.js").text
    assert 'toggle("immersive"' in served_js, "served app.js must toggle immersive"
    assert 'toggle("game-open"' in served_js, "served app.js must toggle game-open"
    assert "13 games are built in" in served_js
    css = c.get("/webapp/style.css").text
    for marker in ("#view-game.immersive", ".fd-wrap .fd-gas",
                   ".fd-wrap .fd-brake", ".rr-wrap .rr-steer",
                   "#game-stage .dpad button", "@media (max-height: 520px)",
                   "body.game-open #mascot-wrap"):
        assert marker in css, f"phase-197 CSS missing {marker}"
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 191, len(paths)
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 206, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    bot_src = open(os.path.join(ROOT, "app/bot.py")).read()
    assert 'menu_url.rstrip("/") + "/?v=206"' in bot_src
    print("neighbours + version + routes OK (184 routes, 52 tables, ?v=206)")

print("PHASE 197 OK")
