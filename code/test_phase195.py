"""Phase-195 tests: Forest Drive — 3D autumn-forest driving game in the
Games section (owner, Nov 27, 11:08 Dhaka: "Game Section এ এটা এড করবা").

The reference video's React + framer-motion game is rebuilt in our
stack (vanilla JS + vendored Three.js r149, no React, no CDN): a red
jeep on a dirt-road loop through low-poly autumn trees, a lake, chase
camera, minimap, speed in km/h, WASD/arrows + touch buttons. Arcade
physics: gas/brake/reverse, speed-sensitive steering, grass slows you
down, trees stop you. Best speed per account (nxGet/nxSet, like
Archery's best) — games award no points. The loop pauses on
visibilitychange and on leaving the view; cleanup cancels rAF,
removes listeners and disposes the renderer.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase195.db"
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


def _extract_game_src():
    js = open(os.path.join(ROOT, "webapp/games.js")).read()
    start = js.index("// --------------------------------------------- Phase 195: Forest Drive --")
    end = js.index("// Built last: every game above must be registered first.")
    assert 0 <= start < end, (start, end)
    src = js[start:end]
    assert 'id: "forest-drive"' in src, "forest-drive id missing"
    assert '"Forest Drive"' in src, "title missing"
    assert "requestAnimationFrame" in src, "rAF loop missing"
    assert "visibilitychange" in src, "hidden-tab pause missing"
    assert "renderer.dispose" in src, "renderer dispose missing"
    assert "nx_forestdrive_best" in src, "per-account best missing"
    assert "drawMinimap" in src and "fd-map" in src and "fd-speed" in src, \
        "minimap/speed HUD missing"
    assert "CanvasTexture" in src, "ground canvas texture missing"
    # No React, no CDN: the video's stack is NOT reused.
    assert 'from "react"' not in src and "from 'react'" not in src, \
        "React import must not appear"
    assert "framer-motion" not in src, "framer-motion must not appear"
    assert "https://" not in src and "http://" not in src, \
        "no remote URLs in the game"
    assert "unpkg" not in src and "cdnjs" not in src, "no CDN in the game"
    return src


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
  MeshLambertMaterial: function (p) { return mkMat("lambert", p); },
  MeshStandardMaterial: function (p) { return mkMat("standard", p); },
  CanvasTexture: function (cv) { const t = { canvas: cv, encoding: null, disposed: false, dispose() { t.disposed = true; } }; created.textures.push(t); return t; },
  Vector3: function (x, y, z) { return mkVec3(x, y, z); },
};
'''

HARNESS_MAIN = r'''
(async () => {
  const def = GameRegistry[0];
  assert(def, "forest-drive registered");
  assert(def.id === "forest-drive", "id forest-drive, got " + def.id);
  assert(def.icon.includes("<svg") && def.icon.includes("E5484D")
      && def.icon.includes("6B7280"), "jeep-on-road icon");
  assert(def.name === "Forest Drive", "name");
  assert(def.title === "Forest Drive", "title");
  assert(def.desc.includes("jeep") && def.desc.includes("90 km/h"), "desc names the jeep + top speed");
  assert(def.help.includes("WASD") && def.help.includes("GAS"), "help names keyboard + touch");
  const stage = makeEl("div");
  let scoreText = "";
  const cleanup = def.start(stage, (s) => { scoreText = s; });
  assert(typeof cleanup === "function", "start returns cleanup");
  assert(cleanup._fd, "test hook present");
  assert(findByClass(stage, "fd-wrap").length === 1, "fd-wrap present");
  assert(findByClass(stage, "fd-canvas").length === 1, "game canvas present");
  assert(findByClass(stage, "fd-panel").length === 1, "controls panel present");
  assert(findByClass(stage, "fd-map").length === 1, "minimap present");
  assert(findByClass(stage, "fd-speed").length === 1, "speed display present");
  assert(findByClass(stage, "fd-touch").length === 1, "touch controls present");
  ["◀", "▶", "BRAKE", "GAS"].forEach((l) => assert(findBtn(stage, l), "touch button " + l + " present"));
  assert(created.renderers.length === 1, "one renderer created");
  assert(created.meshes.length >= 190, "scene has 190+ meshes, got " + created.meshes.length);
  assert(created.geometries.length >= 16, "geometries built, got " + created.geometries.length);
  assert(created.textures.length === 1, "ground canvas texture created");
  assert(cleanup._fd.trees().length === 64, "64 trees placed");
  assert(scoreText === "🚗 0 km/h · Best: 0 km/h", "initial score, got " + scoreText);
  const speedB = findByClass(stage, "fd-speed")[0].children[0];
  assert(speedB.textContent === "0", "speed starts at 0");
  stepFrames(10, 16);
  assert(created.renderCalls >= 10, "frames render, got " + created.renderCalls);
  fireKey("keydown", "KeyW");
  stepFrames(60, 16);
  let st = cleanup._fd.state();
  assert(st.speed > 5, "jeep accelerates, speed " + st.speed);
  assert(+speedB.textContent > 0, "speed HUD updates, got " + speedB.textContent);
  assert(st.best > 0, "best speed recorded");
  assert(scoreText.includes("Best: "), "score shows best");
  const h0 = st.heading;
  fireKey("keydown", "ArrowLeft");
  stepFrames(30, 16);
  st = cleanup._fd.state();
  assert(st.heading !== h0, "steering changes heading");
  fireKey("keyup", "ArrowLeft");
  fireKey("keyup", "KeyW");
  const spBefore = st.speed;
  fireKey("keydown", "KeyS");
  stepFrames(30, 16);
  st = cleanup._fd.state();
  assert(st.speed < spBefore, "brake slows the jeep");
  fireKey("keyup", "KeyS");
  fireKey("keyup", "KeyW");
  cleanup._fd.teleport(0, 0, 0);
  fireKey("keydown", "KeyW");
  stepFrames(30, 16);
  const kmhOff = Math.round(Math.abs(cleanup._fd.state().speed) * 3.6);
  fireKey("keyup", "KeyW");
  cleanup._fd.teleport(58, 0, 0);
  fireKey("keydown", "KeyW");
  stepFrames(30, 16);
  const kmhOn = Math.round(Math.abs(cleanup._fd.state().speed) * 3.6);
  fireKey("keyup", "KeyW");
  assert(kmhOn > kmhOff + 5, "road faster than grass: road " + kmhOn + " vs grass " + kmhOff);
  const tr = cleanup._fd.trees()[0];
  cleanup._fd.teleport(tr.x, tr.z, 0);
  fireKey("keydown", "KeyW");
  stepFrames(10, 16);
  st = cleanup._fd.state();
  const dTree = Math.hypot(st.x - tr.x, st.z - tr.z);
  assert(dTree >= 2.5, "tree pushes the jeep out, dist " + dTree);
  assert(Math.abs(st.speed) < 5, "tree stops the jeep, speed " + st.speed);
  fireKey("keyup", "KeyW");
  cleanup._fd.teleport(58, 0, 0);
  const gasBtn = findBtn(stage, "GAS");
  gasBtn._fire("pointerdown", { preventDefault() {} });
  stepFrames(30, 16);
  assert(cleanup._fd.state().speed > 2, "GAS touch button accelerates");
  gasBtn._fire("pointerup", { preventDefault() {} });
  const leftBtn = findBtn(stage, "◀");
  const h1 = cleanup._fd.state().heading;
  leftBtn._fire("pointerdown", { preventDefault() {} });
  stepFrames(20, 16);
  assert(cleanup._fd.state().heading !== h1, "◀ touch button steers");
  leftBtn._fire("pointerup", { preventDefault() {} });
  const mapCv = findByClass(stage, "fd-map")[0];
  const mcalls = mapCv._ctx.calls;
  assert(mcalls.includes("ellipse"), "minimap draws the road");
  assert(mcalls.filter((c) => c === "arc").length >= 2, "minimap draws lake + jeep dot");
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
  console.log("HARNESS OK (forest-drive: scene, drive, steer, brake, grass, trees, touch, minimap, pause, cleanup, no-WebGL)");
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_node_harness():
    src = _extract_game_src()
    harness = HARNESS_PRELUDE + src + HARNESS_MAIN
    path = "/tmp/t195_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("node harness OK (forest-drive: scene, drive, steer, brake, grass, trees, touch, minimap, pause, cleanup, no-WebGL)")


with TestClient(app) as c:
    # 1. JS parses (node).
    for f in ("webapp/app.js", "webapp/games.js"):
        r = subprocess.run(["node", "--check", os.path.join(ROOT, f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    print("node --check OK (games.js + app.js parse)")

    # 2. Node harness: real game start against DOM + THREE stubs.
    _run_node_harness()

    # 3. Static: 13 games, Nexa + mascot know the 13th, no points.
    games_js = open(os.path.join(ROOT, "webapp/games.js")).read()
    assert games_js.count("registerGame({") == 13, games_js.count("registerGame({")
    js = open(os.path.join(ROOT, "webapp/app.js")).read()
    assert "13 games are built in" in js, "mascot tip must say 13 games"
    assert '"12 games"' not in js, "old 12-games tip must be gone"
    main_py = open(os.path.join(ROOT, "app/main.py")).read()
    assert "13 games" in main_py and "Forest Drive" in main_py, \
        "Nexa must know 13 games incl. Forest Drive"
    assert "১৩টা গেম" in main_py, "Nexa bn answer must say ১৩টা গেম"
    assert '"12 games"' not in main_py, "old 12-games Nexa text must be gone"
    assert "১২টা গেম" not in main_py, "old ১২টা Nexa text must be gone"
    print("static OK (13 games registered; Nexa + mascot updated; no points)")

    # 4. Served assets: version + markers + neighbours.
    html = c.get("/webapp/").text
    assert html.count("?v=202") == 10, html.count("?v=202")
    assert "?v=19" + "4" not in html
    assert "app.js?v=202" in html and "style.css?v=202" in html
    assert "games.js?v=202" in html and "three.min.js?v=202" in html
    served_games = c.get("/webapp/games.js").text
    for marker in ("forest-drive", "Forest Drive", "fd-map", "fd-speed",
                   "drawMinimap", "roadDist", "nx_forestdrive_best",
                   "visibilitychange", "renderer.dispose",
                   "requestAnimationFrame", "CanvasTexture"):
        assert marker in served_games, marker
    assert "from \"react\"" not in served_games, "no React in served games.js"
    assert "framer-motion" not in served_games, "no framer-motion in served games.js"
    served_js = c.get("/webapp/app.js").text
    assert "13 games are built in" in served_js
    css = c.get("/webapp/style.css").text
    for marker in (".fd-wrap", ".fd-canvas", ".fd-panel", ".fd-map",
                   ".fd-speed", ".fd-touch", ".fd-btn", ".fd-gas",
                   ".fd-brake", "@media (max-width: 380px)"):
        assert marker in css, f"forest-drive CSS missing {marker}"
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 193, len(paths)
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 202, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    bot_src = open(os.path.join(ROOT, "app/bot.py")).read()
    assert 'menu_url.rstrip("/") + "/?v=202"' in bot_src
    print("neighbours + version + routes OK (184 routes, 52 tables, ?v=202)")

print("PHASE 195 OK")
