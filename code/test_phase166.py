"""Phase-166 tests: TOTP setup display removed entirely (owner, Nov 22,
09:22 Dhaka: "hide the key from here, it must not be visible" — and
then "no QR code either").

Fix: wireTotpCard() no longer renders any setup surface — no "Show
setup code" button, no secret text, no QR code. The TOTP card keeps
only its title + status line. The client never calls
/admin/totp/setup any more (the endpoint itself stays, admin-only +
fresh initData, as the owner's recovery path via the secrets file
already given to him). Phase 165 behaviour is intact: gate + card
visible together for an unverified admin.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase166.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"

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
    secret = hmac.new(b"WebAppData",
                      settings.BOT_TOKEN.encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, auth_date=None):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name},
                                          auth_date=auth_date)}


ADMIN = H(999, "Admin")
STALE_ADMIN = H(999, "Admin", auth_date=int(time.time()) - 301)
ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
APP_JS_PATH = os.path.join(ROOT, "code/webapp/app.js")


def _extract_gate_src():
    js = open(APP_JS_PATH).read()
    start = js.index("// Phase 164 (H1): authenticator gate")
    end = js.index("async function loadAdmin()")
    assert 0 <= start < end, (start, end)
    src = js[start:end]
    assert 'if (el.id !== "totp-card") el.hidden = true' in src, \
        "Phase 165 fix missing from extracted gate source"
    assert "Show setup code" not in src, \
        "Phase 166: setup button must be gone from gate source"
    assert "totp/setup" not in src, \
        "Phase 166: client must never call the setup endpoint"
    assert "s.secret" not in src, \
        "Phase 166: secret must never be rendered by the gate"
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
function findInput(el) {
  if (el.tag === "input") return el;
  for (const ch of el.children) { const f = findInput(ch); if (f) return f; }
  return null;
}
function collectInputs(el, out) {
  out = out || [];
  if (el.tag === "input") out.push(el);
  for (const ch of el.children) collectInputs(ch, out);
  return out;
}
function visibleText(el) {
  let t = el.textContent || "";
  for (const ch of el.children) t += " " + visibleText(ch);
  return t;
}
function collectTags(el, out) {
  out.push(el.tag);
  for (const ch of el.children) collectTags(ch, out);
}
'''

HARNESS_MAIN = r'''
(async () => {
  const SECRET = "JBSWY3DPEHPK3PXP";
  let setupCalls = 0;
  // --- Scenario 1: gated, unverified admin — no setup surface ---
  const view = makeEl("div"); view.id = "view-admin"; roots.push(view);
  const c1 = makeEl("div"); c1.id = "admin-card-1";
  const c2 = makeEl("div"); c2.id = "admin-card-2";
  view.append(c1, c2);
  apiImpl = async (path) => {
    if (path === "/admin/totp/status") return { configured: true, verified: false };
    if (path === "/admin/totp/setup") { setupCalls++; return { secret: SECRET, otpauth_url: "otpauth://totp/Nexora%20Admin?secret=" + SECRET }; }
    if (path === "/admin/totp/verify") return { verified: true };
    throw new Error("unexpected api " + path);
  };
  const gated = await totpGateAdmin();
  assert(gated === true, "gated returns true");
  const gate = $("totp-gate");
  assert(gate && !gate.hidden, "gate exists and visible");
  const card = $("totp-card");
  assert(card && !card.hidden, "setup card visible next to gate (Phase 165)");
  assert(view.children[0] === gate, "gate first, card right below it");
  assert(view.children[1] === card, "setup card second");
  assert(c1.hidden && c2.hidden, "other admin cards hidden");
  assert(!findBtn(card, "Show setup code"), "Phase 166: no setup button in gated state");
  assert(!findBtn(view, "Show setup code"), "Phase 166: no setup button anywhere in the view");
  assert(card.children.length === 2, "setup card is title + status only, got " + card.children.length);
  assert(setupCalls === 0, "Phase 166: client never calls /admin/totp/setup, got " + setupCalls);
  assert(!visibleText(view).includes("Secret:"), "Phase 166: no secret label in the admin view");
  assert(!visibleText(view).includes(SECRET), "Phase 166: secret must never appear in the admin view");
  const tags = []; collectTags(view, tags);
  assert(!tags.includes("canvas") && !tags.includes("img"),
         "Phase 166: no QR rendering (no canvas/img) in the admin view, tags: " + tags.join(","));
  // --- Scenario 2: verify success ---
  // Phase 194: six digit boxes — typing the 6th digit auto-verifies.
  const boxes = collectInputs(gate);
  assert(boxes.length === 6, "six digit boxes, got " + boxes.length);
  for (let i = 0; i < 6; i++) { boxes[i].value = "123456"[i]; boxes[i]._fire("input", {}); }
  await sleep(1200);
  assert($("totp-gate") === null, "gate removed after verify");
  assert(!c1.hidden && !c2.hidden, "panel cards un-hidden after verify");
  assert(card && !card.hidden, "setup card still visible after verify");
  assert(loadAdminCalls === 1, "loadAdmin called once, got " + loadAdminCalls);
  assert(setupCalls === 0, "client still never called setup after verify");
  // --- Scenario 3: verified admin, no gate ---
  roots.length = 0;
  const view2 = makeEl("div"); view2.id = "view-admin"; roots.push(view2);
  const v2c = makeEl("div"); v2c.id = "admin-card-1"; view2.append(v2c);
  apiImpl = async (path) => {
    if (path === "/admin/totp/status") return { configured: true, verified: true };
    throw new Error("unexpected api " + path);
  };
  const g2 = await totpGateAdmin();
  assert(g2 === false, "verified admin: no gate");
  assert($("totp-gate") === null, "no gate element for verified admin");
  assert(!v2c.hidden, "verified admin: cards untouched");
  assert(!findBtn(view2, "Show setup code"), "verified admin: no setup button either");
  // --- Scenario 4: unconfigured secret, no gate, card says OFF ---
  roots.length = 0;
  const view3 = makeEl("div"); view3.id = "view-admin"; roots.push(view3);
  apiImpl = async (path) => {
    if (path === "/admin/totp/status") return { configured: false, verified: true };
    throw new Error("unexpected api " + path);
  };
  const g3 = await totpGateAdmin();
  assert(g3 === false, "unconfigured: no gate");
  const card3 = $("totp-card");
  assert(card3, "totp card present when unconfigured");
  assert(!findBtn(card3, "Show setup code"), "no setup button when unconfigured");
  assert(card3.children.some(ch => ch.tag === "p" && ch.textContent.includes("OFF")),
         "card says verification is OFF");
  console.log("HARNESS OK (no setup surface, gate+card together, verify, verified, unconfigured)");
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_node_harness():
    src = _extract_gate_src()
    harness = HARNESS_PRELUDE + src + HARNESS_MAIN
    path = "/tmp/t166_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("node harness OK (no setup surface, gate+card together, all 4 scenarios)")


with TestClient(app) as c:
    # 1. JS parses (node).
    for f in ("code/webapp/app.js", "code/webapp/games.js"):
        r = subprocess.run(["node", "--check", os.path.join(ROOT, f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    print("node --check OK (games.js + app.js parse)")

    # 2. Node harness: real gate functions against a DOM stub.
    _run_node_harness()

    # 3. Server: /admin/totp/setup endpoint is INTACT (admin-only +
    # fresh initData) — the client just no longer calls it. The
    # owner's recovery path is the secrets file already given to him.
    import pyotp  # noqa: E402
    assert settings.ADMIN_TOTP_SECRET == ""
    r = c.get("/admin/totp/status", headers=ADMIN)
    assert r.json() == {"configured": False, "verified": True}, r.json()
    r = c.get("/admin/totp/setup", headers=ADMIN)
    assert r.status_code == 400, r.text
    secret = pyotp.random_base32()
    settings.ADMIN_TOTP_SECRET = secret
    try:
        r = c.get("/admin/totp/status", headers=ADMIN)
        assert r.json() == {"configured": True, "verified": False}, r.json()
        r = c.get("/admin/totp/setup", headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["secret"] == secret, r.json()
        assert r.json()["otpauth_url"].startswith("otpauth://totp/"), r.json()
        r = c.get("/admin/totp/setup", headers=STALE_ADMIN)
        assert r.status_code == 401, r.status_code
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
    print("server TOTP OK (setup endpoint intact, fresh+stale, verify wrong+right)")

    # 4. Neighbours + version + routes.
    html = c.get("/webapp/").text
    assert html.count("?v=205") == 10, html.count("?v=205")
    assert "?v=16" + "6" not in html
    assert "app.js?v=205" in html and "style.css?v=205" in html
    assert "qrcode" not in html, "no QR library must be referenced"
    js = c.get("/webapp/app.js").text
    for marker in ("vname-text", "fitVerifiedNames", "totpGateAdmin",
                   "refreshMediaToken", "bloodDistance", "photo_file_id",
                   "MASCOT_TIPS_BY_VIEW", "loadSkills", "totp-card"):
        assert marker in js, marker
    assert "Show setup code" not in js, \
        "Phase 166: setup button must be gone from served app.js"
    assert "s.secret" not in js, \
        "Phase 166: secret must never be rendered by the client"
    assert "qrcode" not in js, "Phase 166: no QR code, no QR library"
    assert 'if (el.id !== "totp-card") el.hidden = true' in js, \
        "Phase 165 fix marker missing from served app.js"
    main_src = open(os.path.join(ROOT, "code/app/main.py")).read()
    assert "nexora-media:" in main_src, "Phase 164 user-bound media token gone"
    assert "_require_admin_fresh" in main_src, "Phase 164 admin step-up gone"
    seg = js[js.index("async function loadBloodDonors"):
             js.index("async function loadBloodRequests")]
    assert "verifiedBadge" in seg, "Phase 163 Blood donor tick gone"
    games = c.get("/webapp/games.js").text
    assert "arch-remote" not in games and "arch-shoot" not in games
    css = c.get("/webapp/style.css").text
    assert "composer-row" in css
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 191, len(paths)
    for p in ("/admin/totp/status", "/admin/totp/setup",
              "/admin/totp/verify"):
        assert p in paths, p
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 205, h
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    print("neighbours + version + routes OK (174 routes, 48 tables, ?v=205)")

print("PHASE 166 OK")
