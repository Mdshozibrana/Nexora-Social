"""Phase-194 tests: glassy OTP gate for Admin Panel TOTP verification
(owner, Nov 27, 11:03 Dhaka: put the "Glassy OTP V4" video's OTP UI
on the Admin Panel entry gate).

The gate's single input + Verify button become six glassy digit
boxes: typing auto-advances, Backspace on an empty box moves back
and clears the previous one, pasting a 6-digit code fills all boxes,
a full code auto-verifies (no button). Wrong code: shake + red tint,
server error shown, boxes cleared, focus back to box 1. Success:
green check + "Verified" + confetti burst, then the panel opens.
The video shows 4 boxes; TOTP codes are 6 digits, so 6 boxes here.
Gating logic (Phases 164/165/166), the verify POST, and the server
rate limit are unchanged; no new routes, no schema change.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase194.db"
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
from app.main import _TOTP_VERIFIED  # noqa: E402
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
SECRET = "JBSWY3DPEHPK3PXP"


def _extract_gate_src():
    js = open(os.path.join(ROOT, "webapp/app.js")).read()
    start = js.index("// Phase 164 (H1): authenticator gate")
    end = js.index("async function loadAdmin()")
    assert 0 <= start < end, (start, end)
    src = js[start:end]
    # Phase 165/166 guards stay: gate hides all but the totp-card, no
    # setup surface, no secret anywhere.
    assert 'if (el.id !== "totp-card") el.hidden = true' in src
    assert "Show setup code" not in src
    assert "totp/setup" not in src
    assert "s.secret" not in src
    # Phase 194 markers.
    assert "totp-glass" in src, "glassy gate class missing"
    assert "totp-digit" in src, "digit boxes missing"
    assert '"one-time-code"' in src, "autocomplete one-time-code missing"
    assert '"Verify"' not in src, "old Verify button must be gone"
    assert "totp-code" not in src, "old single input id must be gone"
    assert '"totp-shake"' in src and '"totp-error"' in src
    assert '"totp-success"' in src and '"totp-confetti"' in src
    assert '"/admin/totp/verify", { method: "POST"' in src, \
        "verify POST unchanged"
    assert "JSON.stringify({ code })" in src, "joined 6-digit code posted"
    return src


HARNESS_PRELUDE = r'''
"use strict";
const roots = [];
function makeEl(tag) {
  const el = {
    tag, children: [], hidden: false, id: "", className: "",
    textContent: "", value: "", type: "", inputMode: "",
    maxLength: 0, placeholder: "", onclick: null, parent: null,
    style: { setProperty(k, v) { this[k] = v; } },
    dataset: {},
    _handlers: {},
    _cls: new Set(),
    classList: { add(...c) { c.forEach(x => el._cls.add(x)); }, remove(...c) { c.forEach(x => el._cls.delete(x)); }, contains(x) { return el._cls.has(x); } },
    addEventListener(t, fn) { (el._handlers[t] = el._handlers[t] || []).push(fn); },
    _fire(t, ev) { (el._handlers[t] || []).forEach(fn => fn(ev || {})); },
    focus() { focusedEl = el; },
    setAttribute(k, v) { el[k] = v; },
    append(...kids) { for (const k of kids) { k.parent = el; el.children.push(k); } },
    appendChild(k) { k.parent = el; el.children.push(k); return k; },
    prepend(...kids) { for (let i = kids.length - 1; i >= 0; i--) { kids[i].parent = el; el.children.unshift(kids[i]); } },
    remove() { if (el.parent) { const i = el.parent.children.indexOf(el); if (i >= 0) el.parent.children.splice(i, 1); el.parent = null; } },
  };
  return el;
}
const document = { createElement: (t) => makeEl(t) };
function findById(node, id) {
  if (node.id === id) return node;
  for (const ch of node.children) { const f = findById(ch, id); if (f) return f; }
  return null;
}
function $(id) { for (const r of roots) { const f = findById(r, id); if (f) return f; } return null; }
let apiImpl = null;
let focusedEl = null;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
async function api(path, opts) { return apiImpl(path, opts); }
let loadAdminCalls = 0;
async function loadAdmin() { loadAdminCalls++; }
function assert(c, msg) { if (!c) throw new Error("ASSERT FAILED: " + msg); }
function findBtn(el, label) {
  if (el.tag === "button" && el.textContent === label) return el;
  for (const ch of el.children) { const f = findBtn(ch, label); if (f) return f; }
  return null;
}
function collectInputs(el, out) {
  out = out || [];
  if (el.tag === "input") out.push(el);
  for (const ch of el.children) collectInputs(ch, out);
  return out;
}
function findByClass(el, cls, out) {
  out = out || [];
  if ((el.className || "").split(" ").includes(cls)) out.push(el);
  for (const ch of el.children) findByClass(ch, cls, out);
  return out;
}
function visibleText(el) {
  let t = el.textContent || "";
  for (const ch of el.children) t += " " + visibleText(ch);
  return t;
}
function typeDigit(box, d) { box.value = d; box._fire("input", {}); }
function pressBackspace(box) { box._fire("keydown", { key: "Backspace", preventDefault() {} }); }
function pasteInto(box, text) { box._fire("paste", { preventDefault() {}, clipboardData: { getData: () => text } }); }
'''

HARNESS_MAIN = r'''
(async () => {
  function freshView() {
    roots.length = 0;
    const view = makeEl("div"); view.id = "view-admin"; roots.push(view);
    const c1 = makeEl("div"); c1.id = "admin-card-1";
    const c2 = makeEl("div"); c2.id = "admin-card-2";
    view.append(c1, c2);
    return { view, c1, c2 };
  }
  let verifyCalls = [];
  function gatedImpl() {
    return async (path, opts) => {
      if (path === "/admin/totp/status") return { configured: true, verified: false };
      if (path === "/admin/totp/setup") throw new Error("Phase 166: client must not call setup");
      if (path === "/admin/totp/verify") { verifyCalls.push(JSON.parse(opts.body).code); return { verified: true }; }
      throw new Error("unexpected api " + path);
    };
  }
  // --- Scenario 1: gate renders glassy, 6 boxes, no old controls ---
  let s = freshView();
  apiImpl = gatedImpl();
  let gated = await totpGateAdmin();
  assert(gated === true, "gated returns true");
  const gate = $("totp-gate");
  assert(gate && !gate.hidden, "gate exists and visible");
  assert(gate.className.includes("totp-glass"), "gate is the glassy card, got " + gate.className);
  assert(gate.className.includes("card"), "gate keeps the card class");
  const card = $("totp-card");
  assert(card && !card.hidden, "setup card visible next to gate (Phase 165)");
  assert(s.c1.hidden && s.c2.hidden, "other admin cards hidden while gated");
  const boxes = collectInputs(gate);
  assert(boxes.length === 6, "six digit boxes, got " + boxes.length);
  boxes.forEach((b, i) => {
    assert(b.className === "totp-digit", "box " + i + " is a glass digit box");
    assert(b.inputMode === "numeric", "box " + i + " numeric keyboard");
    assert(b.maxLength === 1, "box " + i + " one digit");
    assert(b.autocomplete === "one-time-code", "box " + i + " autocomplete one-time-code");
  });
  assert(!findBtn(gate, "Verify"), "Phase 194: no Verify button any more");
  assert(!$("totp-code"), "Phase 194: no single #totp-code input any more");
  assert(visibleText(gate).includes("Admin verification"), "title kept");
  assert(visibleText(gate).includes("6-digit code from your authenticator app"), "hint kept");
  assert(!visibleText(gate).includes("Secret:"), "no secret label on the gate");
  assert(!visibleText(gate).includes("JBSWY3DPEHPK3PXP"), "secret never appears");
  assert(focusedEl === boxes[0], "first box focused on open");
  // --- Scenario 2: typing auto-advances + auto-verifies + success ---
  verifyCalls = [];
  const before = loadAdminCalls;
  for (let i = 0; i < 6; i++) {
    typeDigit(boxes[i], "123456"[i]);
    if (i < 5) assert(focusedEl === boxes[i + 1], "digit " + i + " advances focus to box " + (i + 1));
  }
  assert(verifyCalls.length === 1 && verifyCalls[0] === "123456",
         "6th digit auto-verifies with the joined code, got " + JSON.stringify(verifyCalls));
  await sleep(50);
  const ok = findByClass(gate, "totp-success");
  assert(ok.length === 1, "success state shown");
  assert(visibleText(ok[0]).includes("Verified"), "success says Verified");
  const tick = findByClass(gate, "totp-check");
  assert(tick.length === 1 && tick[0].textContent === "✓", "green check circle shown");
  const pieces = findByClass(gate, "totp-confetti-piece");
  assert(pieces.length === 24, "confetti burst has 24 pieces, got " + pieces.length);
  assert(pieces[0].style.left && pieces[0].style["--dx"], "confetti pieces positioned");
  await sleep(1200);
  assert($("totp-gate") === null, "gate removed after success");
  assert(!s.c1.hidden && !s.c2.hidden, "panel cards un-hidden after verify");
  assert(loadAdminCalls === before + 1, "loadAdmin called once");
  // --- Scenario 3: Backspace on an empty box moves back + clears ---
  s = freshView();
  apiImpl = gatedImpl();
  verifyCalls = [];
  gated = await totpGateAdmin();
  const g3 = $("totp-gate");
  const b3 = collectInputs(g3);
  typeDigit(b3[0], "1");
  typeDigit(b3[1], "2");
  assert(focusedEl === b3[2], "focus on box 3 after two digits");
  pressBackspace(b3[2]);
  assert(focusedEl === b3[1] && b3[1].value === "", "backspace on empty box 3 clears box 2 + focuses it");
  assert(b3[0].value === "1", "box 1 untouched");
  pressBackspace(b3[1]);
  assert(focusedEl === b3[0] && b3[0].value === "", "backspace on empty box 2 clears box 1 + focuses it");
  assert(verifyCalls.length === 0, "no verify during backspace");
  // --- Scenario 4: paste fills all 6 and auto-verifies ---
  s = freshView();
  apiImpl = gatedImpl();
  verifyCalls = [];
  gated = await totpGateAdmin();
  const g4 = $("totp-gate");
  const b4 = collectInputs(g4);
  pasteInto(b4[0], "654321");
  assert(b4.map(b => b.value).join("") === "654321", "paste fills all six boxes");
  assert(verifyCalls.length === 1 && verifyCalls[0] === "654321",
         "paste auto-verifies with the pasted code, got " + JSON.stringify(verifyCalls));
  await sleep(1200);
  assert($("totp-gate") === null, "gate removed after pasted verify");
  // --- Scenario 5: wrong code shakes, shows the error, clears, refocuses ---
  s = freshView();
  let wrongFirst = true;
  apiImpl = async (path, opts) => {
    if (path === "/admin/totp/status") return { configured: true, verified: false };
    if (path === "/admin/totp/verify") {
      verifyCalls.push(JSON.parse(opts.body).code);
      if (wrongFirst) { wrongFirst = false; throw new Error("Wrong code — try again."); }
      return { verified: true };
    }
    throw new Error("unexpected api " + path);
  };
  verifyCalls = [];
  gated = await totpGateAdmin();
  const g5 = $("totp-gate");
  const b5 = collectInputs(g5);
  const row5 = findByClass(g5, "totp-otp-row")[0];
  for (let i = 0; i < 6; i++) typeDigit(b5[i], "9");
  await sleep(50);
  assert(verifyCalls.length === 1 && verifyCalls[0] === "999999", "wrong code posted once");
  const msg5 = $("totp-msg");
  assert(msg5 && msg5.textContent.includes("Wrong code"), "server error shown, got " + (msg5 && msg5.textContent));
  assert(row5.classList.contains("totp-shake"), "row shakes on wrong code");
  assert(b5.every(b => b.classList.contains("totp-error")), "boxes go red on wrong code");
  assert(b5.every(b => b.value === ""), "boxes cleared after wrong code");
  assert(focusedEl === b5[0], "focus back on first box after wrong code");
  await sleep(600);
  assert(!row5.classList.contains("totp-shake"), "shake class removed after animation");
  for (let i = 0; i < 6; i++) typeDigit(b5[i], "123456"[i]);
  await sleep(1200);
  assert($("totp-gate") === null, "gate removed after correct retry");
  assert(verifyCalls.length === 2, "retry posts once more");
  // --- Scenario 6: verified admin — no gate, panel untouched ---
  s = freshView();
  apiImpl = async (path) => {
    if (path === "/admin/totp/status") return { configured: true, verified: true };
    throw new Error("unexpected api " + path);
  };
  const g6 = await totpGateAdmin();
  assert(g6 === false, "verified admin: no gate");
  assert($("totp-gate") === null, "no gate element for verified admin");
  assert(!s.c1.hidden, "verified admin: cards untouched");
  console.log("HARNESS OK (glassy 6-box gate, advance, backspace, paste, wrong+retry, verified)");
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_node_harness():
    src = _extract_gate_src()
    harness = HARNESS_PRELUDE + src + HARNESS_MAIN
    path = "/tmp/t194_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("node harness OK (glassy 6-box gate, all 6 scenarios)")


with TestClient(app) as c:
    # 1. JS parses (node).
    for f in ("webapp/app.js", "webapp/games.js"):
        r = subprocess.run(["node", "--check", os.path.join(ROOT, f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    print("node --check OK (games.js + app.js parse)")

    # 2. Node harness: real gate functions against a DOM stub.
    _run_node_harness()

    # 3. Server: verify endpoint unchanged — wrong code 400, right
    # code 200 (the gate posts the joined 6-digit code as before).
    import pyotp  # noqa: E402
    assert settings.ADMIN_TOTP_SECRET == ""
    r = c.get("/admin/totp/status", headers=ADMIN)
    assert r.json() == {"configured": False, "verified": True}, r.json()
    secret = pyotp.random_base32()
    settings.ADMIN_TOTP_SECRET = secret
    try:
        r = c.get("/admin/totp/status", headers=ADMIN)
        assert r.json() == {"configured": True, "verified": False}, r.json()
        r = c.get("/admin/health", headers=ADMIN)
        assert r.status_code == 403, r.status_code
        assert "Admin verification required" in r.json()["detail"], r.text
        real = pyotp.TOTP(secret).now()
        wrong = "000000" if real != "000000" else "111111"
        r = c.post("/admin/totp/verify", headers=ADMIN, json={"code": wrong})
        assert r.status_code == 400, r.text
        r = c.post("/admin/totp/verify", headers=ADMIN, json={"code": real})
        assert r.status_code == 200 and r.json()["verified"] is True, r.text
        r = c.get("/admin/totp/status", headers=ADMIN)
        assert r.json() == {"configured": True, "verified": True}, r.json()
    finally:
        settings.ADMIN_TOTP_SECRET = ""
        _TOTP_VERIFIED.clear()
    print("server TOTP OK (verify wrong+right, gate still enforced)")

    # 4. Served assets: glassy styles + version + neighbours.
    html = c.get("/webapp/").text
    assert html.count("?v=201") == 10, html.count("?v=201")
    assert "?v=19" + "3" not in html
    assert "app.js?v=201" in html and "style.css?v=201" in html
    assert "qrcode" not in html, "no QR library must be referenced"
    js = c.get("/webapp/app.js").text
    for marker in ("vname-text", "fitVerifiedNames", "totpGateAdmin",
                   "refreshMediaToken", "bloodDistance", "photo_file_id",
                   "MASCOT_TIPS_BY_VIEW", "loadSkills", "totp-card",
                   "totp-glass", "totp-digit", "totp-success"):
        assert marker in js, marker
    assert '"Verify"' not in js[js.index("async function totpGateAdmin"):
                                 js.index("async function loadAdmin()")], \
        "Phase 194: old Verify button must be gone from the gate"
    assert "Show setup code" not in js, \
        "Phase 166: setup button must be gone from served app.js"
    assert "s.secret" not in js, \
        "Phase 166: secret must never be rendered by the client"
    assert 'if (el.id !== "totp-card") el.hidden = true' in js, \
        "Phase 165 fix marker missing from served app.js"
    css = c.get("/webapp/style.css").text
    for marker in (".totp-glass", "backdrop-filter", ".totp-digit:focus",
                   "#3B82F6", "@keyframes totp-shake",
                   "@keyframes totp-confetti-fall", ".totp-success",
                   "@media (max-width: 380px)"):
        assert marker in css, f"glassy CSS missing {marker}"
    assert "44px" in css and "38px" in css, \
        "digit boxes must shrink at 360px (44px -> 38px)"
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 193, len(paths)
    for p in ("/admin/totp/status", "/admin/totp/setup",
              "/admin/totp/verify"):
        assert p in paths, p
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 201, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    bot_src = open(os.path.join(ROOT, "app/bot.py")).read()
    assert 'menu_url.rstrip("/") + "/?v=201"' in bot_src
    print("neighbours + version + routes OK (184 routes, 52 tables, ?v=201)")

print("PHASE 194 OK")
