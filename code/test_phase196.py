"""Phase-196 tests: Runner Rush — the 13th Games-section game (owner,
Nov 27, 13:03 Dhaka: two reference videos merged into ONE game).

The bike runner over water and the carrot runner on a sky track are
rebuilt in our stack (vanilla JS + vendored Three.js r149, no React,
no CDN) as one game with a mode picker: Bike Run (teal lagoon, sunset
sky, amber track, teal tide gates, golden buoy arch + treasure chest)
and Carrot Run (purple dusk, mint track, star saws, juice jar). A
shared 3-lane auto-runner engine: steer with arrows / swipe / touch,
collect wheels or carrots, smash numbered walls, dodge saws, finish
for the multiplier. Best level per account (nxGet/nxSet) — games
award no points. The loop pauses on visibilitychange and on leaving
the view; cleanup cancels rAF, removes listeners and disposes the
renderer.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase196.db"
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
    start = js.index("// --------------------------------------------- Phase 196: Runner Rush --")
    end = js.index("// Built last: every game above must be registered first.")
    assert 0 <= start < end, (start, end)
    src = js[start:end]
    assert 'id: "runner-rush"' in src, "runner-rush id missing"
    assert '"Runner Rush"' in src, "title missing"
    assert "requestAnimationFrame" in src, "rAF loop missing"
    assert "visibilitychange" in src, "hidden-tab pause missing"
    assert "renderer.dispose" in src, "renderer dispose missing"
    assert "nx_runnerrush_best" in src, "per-account best missing"
    assert "rr-picker" in src and "rr-hud" in src and "rr-progress" in src, \
        "picker/HUD/progress missing"
    assert "TorusGeometry" in src and "OctahedronGeometry" in src, \
        "wheel/gem geometry missing"
    assert "tide gate" in src and "star saw" in src and "juice jar" in src, \
        "restyled world markers missing"
    assert "CanvasTexture" in src, "number canvas texture missing"
    # No React, no CDN: the videos' stacks are NOT reused.
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

HARNESS_MAIN = r'''
(async () => {
  const def = GameRegistry[0];
  assert(def, "runner-rush registered");
  assert(def.id === "runner-rush", "id runner-rush, got " + def.id);
  assert(def.icon.includes("<svg") && def.icon.includes("F97316"),
      "bike-and-carrot icon");
  assert(def.name === "Runner Rush", "name");
  assert(def.title === "Runner Rush", "title");
  assert(def.desc.includes("lagoon") && def.desc.includes("sky"), "desc names both tracks");
  assert(def.help.includes("swipe") && def.help.includes("walls") && def.help.includes("saws"), "help names steering + both modes");
  const stage = makeEl("div");
  let scoreText = "";
  const cleanup = def.start(stage, (s) => { scoreText = s; });
  assert(typeof cleanup === "function", "start returns cleanup");
  assert(cleanup._rr, "test hook present");
  assert(findByClass(stage, "rr-wrap").length === 1, "rr-wrap present");
  assert(findByClass(stage, "rr-canvas").length === 1, "game canvas present");
  assert(findByClass(stage, "rr-picker").length === 1, "mode picker present");
  const bikeBtn = findBtn(stage, "🚲 Bike Run");
  const carrotBtn = findBtn(stage, "🥕 Carrot Run");
  assert(bikeBtn && carrotBtn, "both mode cards present");
  assert(visibleText(stage).includes("Pedal the lagoon track"), "bike card desc present");
  assert(visibleText(stage).includes("Sprint the sky track"), "carrot card desc present");
  assert(cleanup._rr.mode() === null, "starts at picker");
  assert(cleanup._rr.state().status === "picker", "status picker");
  assert(scoreText.includes("Pick your ride"), "initial score, got " + scoreText);
  assert(!/points/i.test(scoreText), "games award no points");
  assert(created.renderers.length === 1, "one renderer created");
  // --- bike mode ---
  bikeBtn.onclick();
  assert(cleanup._rr.mode() === "bike", "bike mode starts");
  let st = cleanup._rr.state();
  assert(st.status === "running", "bike running");
  assert(st.level === 1 && st.finishZ === -600, "level 1 length 600, finishZ " + st.finishZ);
  assert(findByClass(stage, "rr-picker")[0].hidden === true, "picker hides on start");
  assert(findByClass(stage, "rr-hud").length === 1, "HUD present");
  assert(findByClass(stage, "rr-progress-fill").length === 1, "progress bar present");
  assert(findByClass(stage, "rr-touch").length === 1, "touch controls present");
  assert(findBtn(stage, "◀") && findBtn(stage, "▶"), "steer buttons present");
  assert(findBtn(stage, "‹ Modes"), "Modes button present");
  assert(created.meshes.length >= 60, "bike scene has 60+ meshes, got " + created.meshes.length);
  const rc0 = created.renderCalls;
  stepFrames(10, 16);
  assert(created.renderCalls > rc0, "frames render");
  st = cleanup._rr.state();
  assert(st.z < 0, "bike moves forward, z " + st.z);
  assert(st.speed > 10, "bike speed, got " + st.speed);
  assert(st.nextWall, "a wall spawns ahead");
  assert(st.nextGate, "a multiplier gate spawns ahead");
  cleanup._rr.setCount("wheel", 50);
  // steering: keyboard
  fireKey("keydown", "ArrowLeft");
  stepFrames(15, 16);
  st = cleanup._rr.state();
  assert(st.lane === 0 && st.x < -1, "ArrowLeft steers to lane 0, x " + st.x);
  fireKey("keydown", "ArrowRight");
  fireKey("keydown", "ArrowRight");
  stepFrames(15, 16);
  st = cleanup._rr.state();
  assert(st.lane === 2 && st.x > 1, "ArrowRight steers to lane 2, x " + st.x);
  // swipe on canvas
  const cnv = findByClass(stage, "rr-canvas")[0];
  cnv._fire("touchstart", { touches: [{ clientX: 200, clientY: 100 }] });
  cnv._fire("touchend", { changedTouches: [{ clientX: 120, clientY: 100 }] });
  st = cleanup._rr.state();
  assert(st.lane === 1, "swipe left steers to lane 1");
  // touch button
  findBtn(stage, "▶")._fire("pointerdown", { preventDefault() {} });
  st = cleanup._rr.state();
  assert(st.lane === 2, "▶ touch button steers right");
  // collecting
  cleanup._rr.collect(3);
  st = cleanup._rr.state();
  assert(st.wheels === 53, "collect adds wheels, got " + st.wheels);
  assert(visibleText(stage).includes("🛞 53"), "HUD shows wheels");
  cleanup._rr.collect(2, "gem");
  assert(cleanup._rr.state().gems === 2, "collect adds gems");
  // wall pass: fund the lane-1 panel exactly, drive through
  st = cleanup._rr.state();
  const wallCost = st.nextWall.costs[1];
  cleanup._rr.setCount("wheel", wallCost + 2);
  cleanup._rr.teleport(st.nextWall.z + 1.5, 1);
  stepFrames(12, 16);
  st = cleanup._rr.state();
  assert(st.status === "running", "wall passed, status " + st.status);
  assert(st.wheels === 2, "wall deducts its number, wheels " + st.wheels);
  // wall crash: no wheels left
  cleanup._rr.setCount("wheel", 50);
  let guard = 0;
  while (!cleanup._rr.state().nextWall && guard++ < 40) { cleanup._rr.setCount("wheel", 50); stepFrames(10, 16); }
  st = cleanup._rr.state();
  assert(st.nextWall, "second wall spawns ahead");
  cleanup._rr.setCount("wheel", 0);
  cleanup._rr.hitObstacle();
  st = cleanup._rr.state();
  assert(st.status === "over", "wall crash ends run, status " + st.status);
  assert(visibleText(stage).includes("Crashed"), "crash overlay shows");
  assert(visibleText(stage).includes("tide gate"), "crash names the tide gate");
  assert(findBtn(stage, "↻ Retry"), "Retry button present");
  // retry
  findBtn(stage, "↻ Retry").onclick();
  st = cleanup._rr.state();
  assert(st.status === "running" && st.mode === "bike", "retry restarts bike run");
  assert(st.wheels === 0 && st.z === 0, "retry resets run");
  // finish: bike score = (wheels+gems) x mult
  cleanup._rr.setCount("wheel", 10);
  cleanup._rr.setCount("gem", 2);
  cleanup._rr.setCount("mult", 3);
  cleanup._rr.finish();
  st = cleanup._rr.state();
  assert(st.status === "done", "finish ends run");
  assert(st.score === 36, "bike score (10+2)x3 = 36, got " + st.score);
  assert(st.best === 1, "best level recorded");
  assert(visibleText(stage).includes("Level Clear"), "finish overlay shows");
  assert(visibleText(stage).includes("36"), "finish overlay shows score");
  assert(findBtn(stage, "Next level ›"), "Next level button present");
  assert(findByClass(stage, "rr-confetti").length > 0, "confetti burst on finish");
  // next level
  findBtn(stage, "Next level ›").onclick();
  st = cleanup._rr.state();
  assert(st.status === "running" && st.level === 2, "next level starts level 2");
  assert(st.finishZ === -750, "level 2 length 750, finishZ " + st.finishZ);
  // back to picker
  cleanup._rr.toPicker();
  assert(cleanup._rr.mode() === null, "toPicker clears mode");
  assert(cleanup._rr.state().status === "picker", "back at picker");
  assert(findByClass(stage, "rr-picker")[0].hidden === false, "picker visible again");
  assert(visibleText(stage).includes("Best level: 1"), "picker shows best level");
  // --- carrot mode ---
  const meshesBefore = created.meshes.length;
  carrotBtn.onclick();
  assert(cleanup._rr.mode() === "carrot", "carrot mode starts");
  st = cleanup._rr.state();
  assert(st.status === "running", "carrot running");
  assert(created.meshes.length > meshesBefore + 30, "carrot scene builds, meshes " + created.meshes.length + " vs " + meshesBefore);
  stepFrames(10, 16);
  assert(cleanup._rr.state().z < 0, "carrot runs forward");
  cleanup._rr.setCount("carrot", 50);
  guard = 0;
  while (!cleanup._rr.state().nextSaw && guard++ < 40) { cleanup._rr.setCount("carrot", 50); stepFrames(10, 16); }
  assert(cleanup._rr.state().nextSaw, "a saw spawns ahead");
  cleanup._rr.setCount("carrot", 50);
  // collect carrots + multiplier zones
  cleanup._rr.collect(12);
  st = cleanup._rr.state();
  assert(st.carrots === 62, "collect adds carrots, got " + st.carrots);
  assert(st.mult === 8, "62 carrots -> x8 zone, got " + st.mult);
  cleanup._rr.setCount("carrot", 12);
  assert(cleanup._rr.state().mult === 4, "12 carrots -> x4 zone");
  // checkpoint flag: jump to just before the 150-unit mark, then cross it
  // (re-jump if a saw knocks the run back to the start checkpoint)
  cleanup._rr.teleport(-140, 1);
  guard = 0;
  while (!cleanup._rr.state().nextFlag && guard++ < 30) {
    if (cleanup._rr.state().z > -130) cleanup._rr.teleport(-140, 1);
    cleanup._rr.setCount("carrot", 50);
    stepFrames(10, 16);
  }
  st = cleanup._rr.state();
  assert(st.nextFlag, "a checkpoint flag spawns");
  const flagZ = st.nextFlag.z;
  cleanup._rr.teleport(flagZ + 1.5, 1);
  stepFrames(12, 16);
  st = cleanup._rr.state();
  assert(st.checkpoint === flagZ, "flag sets checkpoint, got " + st.checkpoint);
  // saw hit: costs 5 carrots, respawns at checkpoint
  guard = 0;
  while (!cleanup._rr.state().nextSaw && guard++ < 40) { cleanup._rr.setCount("carrot", 50); stepFrames(10, 16); }
  st = cleanup._rr.state();
  assert(st.nextSaw, "a saw spawns ahead");
  const sawZ = st.nextSaw.z, sawLane = st.nextSaw.lane;
  cleanup._rr.setCount("carrot", 12);
  cleanup._rr.teleport(sawZ + 1.5, sawLane);
  stepFrames(12, 16);
  st = cleanup._rr.state();
  assert(st.carrots === 7, "saw hit costs 5 carrots, got " + st.carrots);
  assert(st.status === "running", "saw hit does not end run with carrots banked");
  assert(st.z === flagZ, "respawn at checkpoint, z " + st.z + " vs flag " + flagZ);
  stepFrames(40, 16);
  st = cleanup._rr.state();
  assert(st.invuln > 0, "invulnerability blink after respawn");
  assert(st.z < flagZ, "run resumes after respawn");
  // saw hit with too few carrots ends the run
  cleanup._rr.setCount("carrot", 3);
  cleanup._rr.hitObstacle();
  st = cleanup._rr.state();
  assert(st.status === "over", "saw hit with <5 carrots ends run");
  assert(visibleText(stage).includes("Sliced"), "slice crash overlay shows");
  findBtn(stage, "↻ Retry").onclick();
  st = cleanup._rr.state();
  assert(st.status === "running" && st.mode === "carrot", "retry restarts carrot run");
  // edge fall: steer off the track, costs 3 carrots, respawns
  cleanup._rr.setCount("carrot", 10);
  fireKey("keydown", "ArrowLeft");
  stepFrames(5, 16);
  fireKey("keydown", "ArrowLeft");
  stepFrames(40, 16);
  st = cleanup._rr.state();
  assert(st.carrots === 7, "edge fall costs 3 carrots, got " + st.carrots);
  assert(st.lane === 1, "respawn resets to centre lane");
  assert(st.z === 0, "respawn at checkpoint 0 after retry, z " + st.z);
  stepFrames(40, 16);
  assert(cleanup._rr.state().status === "running", "run resumes after edge fall");
  // finish: carrot score = carrots x zone
  cleanup._rr.setCount("carrot", 25);
  cleanup._rr.finish();
  st = cleanup._rr.state();
  assert(st.status === "done", "carrot finish ends run");
  assert(st.mult === 6, "25 carrots -> x6 zone");
  assert(st.score === 150, "carrot score 25x6 = 150, got " + st.score);
  assert(visibleText(stage).includes("150"), "carrot finish overlay shows score");
  cleanup._rr.toPicker();
  assert(cleanup._rr.state().status === "picker", "back at picker after carrot");
  // pause on hidden tab, resume on visible
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
  console.log("HARNESS OK (runner-rush: picker, bike walls/gates/finish, carrot saws/flags/edge/finish, steer, pause, cleanup, no-WebGL)");
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_node_harness():
    src = _extract_game_src()
    harness = HARNESS_PRELUDE + src + HARNESS_MAIN
    path = "/tmp/t196_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("node harness OK (runner-rush: picker, bike walls/gates/finish, carrot saws/flags/edge/finish, steer, pause, cleanup, no-WebGL)")


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
    assert "Runner Rush" in js, "mascot tip must name Runner Rush"
    assert "12 games" not in js, "old 12-games tip must be gone"
    main_py = open(os.path.join(ROOT, "app/main.py")).read()
    assert "13 games" in main_py and "Runner Rush" in main_py, \
        "Nexa must know 13 games incl. Runner Rush"
    assert "১৩টা গেম" in main_py, "Nexa bn answer must say ১৩টা গেম"
    assert "12 games" not in main_py, "old 12-games Nexa text must be gone"
    assert "১২টা গেম" not in main_py, "old ১২টা Nexa text must be gone"
    print("static OK (13 games registered; Nexa + mascot updated; no points)")

    # 4. Served assets: version + markers + neighbours.
    html = c.get("/webapp/").text
    assert html.count("?v=201") == 10, html.count("?v=201")
    assert "?v=19" + "5" not in html
    assert "app.js?v=201" in html and "style.css?v=201" in html
    assert "games.js?v=201" in html and "three.min.js?v=201" in html
    served_games = c.get("/webapp/games.js").text
    for marker in ("runner-rush", "Runner Rush", "rr-picker", "rr-hud",
                   "rr-progress", "nx_runnerrush_best", "tide gate",
                   "star saw", "juice jar", "TorusGeometry",
                   "OctahedronGeometry", "visibilitychange",
                   "renderer.dispose", "requestAnimationFrame",
                   "CanvasTexture"):
        assert marker in served_games, marker
    assert "from \"react\"" not in served_games, "no React in served games.js"
    assert "framer-motion" not in served_games, "no framer-motion in served games.js"
    served_js = c.get("/webapp/app.js").text
    assert "13 games are built in" in served_js
    css = c.get("/webapp/style.css").text
    for marker in (".rr-wrap", ".rr-canvas", ".rr-hud", ".rr-picker",
                   ".rr-pick-card", ".rr-touch", ".rr-btn", ".rr-steer",
                   ".rr-progress", ".rr-progress-fill", ".rr-overlay",
                   ".rr-ov-title", ".rr-confetti", "rr-fall",
                   "@media (max-width: 380px)"):
        assert marker in css, f"runner-rush CSS missing {marker}"
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 193, len(paths)
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 201, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    bot_src = open(os.path.join(ROOT, "app/bot.py")).read()
    assert 'menu_url.rstrip("/") + "/?v=201"' in bot_src
    print("neighbours + version + routes OK (184 routes, 52 tables, ?v=201)")

print("PHASE 196 OK")
