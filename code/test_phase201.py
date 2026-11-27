"""Phase 201 tests: Museum — a member's own 3D gallery (owner order
Nov 27, 18:13 Dhaka; model confirmed 18:24).

Sidebar Museum opens MY museum (hang photos, place furniture,
walk room to room); a profile's Museum button opens THAT member's
museum (view-only). Wall photos come from the owner's own posts /
designs (no new upload path — same rule as Phase 199); furniture
comes from a built-in catalog. Three rooms, four wall frames +
four floor spots each. Visibility reuses the Phase 136/174 rules
(private, block either way, mute). No points, no payments.
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase201.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import (app, _BACKUP_TABLES, _media_visible,  # noqa: E402
                      MUSEUM_ROOMS, MUSEUM_FURNITURE, MUSEUM_SLOTS)
from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402

def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(2011, "Alice", "alice")
BOB = H(2012, "Bob", "bob")
CAROL = H(2013, "Carol", "carol")
DAVE = H(2014, "Dave", "dave")
OFFICIAL = H(1, "Nexora Social", "nexora")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
MAIN = open(os.path.join(ROOT, "code/app/main.py")).read()

c = TestClient(app)


def mk(uid, name, username):
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        u = db.get(models.User, uid)
        assert u is not None, "user %s not created" % uid
        u.username = username
        db.commit()
    finally:
        db.close()


for uid, name, uname in ((2011, "Alice", "alice"), (2012, "Bob", "bob"),
                         (2013, "Carol", "carol"), (2014, "Dave", "dave")):
    mk(uid, name, uname)


def mkpost(headers, caption, photo=None):
    body = {"type": "photo" if photo else "text", "caption": caption}
    if photo:
        body["media_file_id"] = photo
    r = c.post("/posts", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def get_mu(headers, uid):
    return c.get(f"/users/{uid}/museum", headers=headers)


def my_mu(headers):
    r = c.get("/me/museum", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def hang(headers, payload):
    return c.post("/me/museum/items", json=payload, headers=headers)


# --- 1. Constants, routes, backup, RLS role. ---------------------------
assert MUSEUM_ROOMS == ("entrance", "lounge", "family"), MUSEUM_ROOMS
assert MUSEUM_FURNITURE == ("chair", "table", "lamp", "plant", "sofa",
                            "rug"), MUSEUM_FURNITURE
assert MUSEUM_SLOTS == 4, MUSEUM_SLOTS
paths = {rt.path for rt in app.routes}
assert len(paths) == 193, len(paths)
for want in ("/users/{telegram_id}/museum", "/me/museum",
             "/me/museum/items", "/me/museum/items/{item_id}"):
    assert want in paths, want
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert ("museum_items", models.MuseumItem) in _BACKUP_TABLES
ROLE = open(os.path.join(
    ROOT, "code/migrations/phase164_rls_role.sql")).read()
assert "museum_items" in ROLE, "RLS role script lacks museum_items"
# No row-level policy yet for this table either (same gap as
# portfolios) — the role script grants DML only; the policy file
# must not claim otherwise.
RLS = open(os.path.join(
    ROOT, "code/migrations/phase164_rls.sql")).read()
assert "museum_items" not in RLS
print("1. constants + routes 193 + backup 55 + RLS DML OK")

# --- 2. Empty museum: rooms all present, all empty. ----------------------
mine = my_mu(ALICE)
assert mine["user_id"] == 2011 and mine["first_name"] == "Alice", mine
assert mine["username"] == "alice" and mine["is_verified"] is False, mine
assert set(mine["rooms"]) == {"entrance", "lounge", "family"}, mine
assert all(v == [] for v in mine["rooms"].values()), mine
r = get_mu(BOB, 2011)
assert r.status_code == 200, r.text
assert r.json()["rooms"] == mine["rooms"], r.text
r = get_mu(ALICE, 9999)
assert r.status_code == 404, r.text
print("2. empty museum OK")

# --- 3. Hang photos: post / design / raw + bad inputs. -------------------
p_photo = mkpost(ALICE, "Gallery wall", photo="mu_photo_1")
p_text = mkpost(ALICE, "Just words")
db = SessionLocal()
db.add(models.Design(image_file_id="mu_design_1", prompt="Logo mark"))
db.commit()
design_id = db.query(models.Design).filter_by(
    image_file_id="mu_design_1").first().id
db.close()
r = hang(ALICE, {"room": "entrance", "kind": "photo", "slot": 0,
                 "ref_kind": "post", "ref_id": p_photo})
assert r.status_code == 200, r.text
i_post = r.json()
assert i_post["kind"] == "photo" and i_post["slot"] == 0, r.text
assert i_post["image_file_id"] == "mu_photo_1", r.text
assert i_post["ref_kind"] == "post" and i_post["ref_id"] == p_photo, r.text
r = hang(ALICE, {"room": "entrance", "kind": "photo", "slot": 1,
                 "ref_kind": "design", "ref_id": design_id})
assert r.status_code == 200, r.text
assert r.json()["image_file_id"] == "mu_design_1", r.text
r = hang(ALICE, {"room": "lounge", "kind": "photo", "slot": 0,
                 "image_file_id": "mu_photo_1"})
assert r.status_code == 200, r.text
assert r.json()["ref_kind"] is None, r.text
mine = my_mu(ALICE)
assert len(mine["rooms"]["entrance"]) == 2, mine
assert len(mine["rooms"]["lounge"]) == 1, mine
assert mine["rooms"]["family"] == [], mine
# Bad inputs.
for bad, why in (
        ({"room": "attic", "kind": "photo", "slot": 0,
          "image_file_id": "mu_photo_1"}, "bad room"),
        ({"room": "entrance", "kind": "painting", "slot": 0,
          "image_file_id": "mu_photo_1"}, "bad kind"),
        ({"room": "entrance", "kind": "photo", "slot": -1,
          "image_file_id": "mu_photo_1"}, "slot -1"),
        ({"room": "entrance", "kind": "photo", "slot": 4,
          "image_file_id": "mu_photo_1"}, "slot 4"),
        ({"room": "entrance", "kind": "photo", "slot": 2,
          "ref_kind": "post", "ref_id": p_text}, "text post, no photo"),
        ({"room": "entrance", "kind": "photo", "slot": 2,
          "image_file_id": "stranger_photo"}, "not my photo"),
        ({"room": "entrance", "kind": "photo", "slot": 2,
          "ref_kind": "design", "ref_id": 999999}, "design gone"),
        ({"room": "entrance", "kind": "photo", "slot": 2,
          "ref_kind": "statue", "ref_id": 1}, "bad ref_kind")):
    r = hang(ALICE, bad)
    assert r.status_code in (400, 404), (why, r.status_code, r.text)
# Someone else's post cannot be hung on my wall.
p_bob = mkpost(BOB, "Bob's wall", photo="mu_bob_1")
r = hang(ALICE, {"room": "family", "kind": "photo", "slot": 0,
                 "ref_kind": "post", "ref_id": p_bob})
assert r.status_code == 404, r.text
print("3. hang photos + bad inputs OK")

# --- 4. Place furniture + bad type. --------------------------------------
r = hang(ALICE, {"room": "lounge", "kind": "furniture", "slot": 1,
                 "furniture_type": "sofa"})
assert r.status_code == 200, r.text
i_sofa = r.json()
assert i_sofa["kind"] == "furniture", r.text
assert i_sofa["furniture_type"] == "sofa", r.text
assert i_sofa["image_file_id"] is None, r.text
r = hang(ALICE, {"room": "lounge", "kind": "furniture", "slot": 2,
                 "furniture_type": "grand-piano"})
assert r.status_code == 400, r.text
r = hang(ALICE, {"room": "lounge", "kind": "furniture", "slot": 2})
assert r.status_code == 400, r.text
mine = my_mu(ALICE)
assert len(mine["rooms"]["lounge"]) == 2, mine
print("4. place furniture + bad type OK")

# --- 5. Replace on an occupied slot (one row per room+kind+slot). -------
r = hang(ALICE, {"room": "entrance", "kind": "photo", "slot": 0,
                 "image_file_id": "mu_photo_1"})
assert r.status_code == 200, r.text
assert r.json()["id"] != i_post["id"], r.text
mine = my_mu(ALICE)
slot0 = [i for i in mine["rooms"]["entrance"]
         if i["kind"] == "photo" and i["slot"] == 0]
assert len(slot0) == 1, mine
r = hang(ALICE, {"room": "lounge", "kind": "furniture", "slot": 1,
                 "furniture_type": "chair"})
assert r.status_code == 200, r.text
mine = my_mu(ALICE)
slot1 = [i for i in mine["rooms"]["lounge"]
         if i["kind"] == "furniture" and i["slot"] == 1]
assert len(slot1) == 1 and slot1[0]["furniture_type"] == "chair", mine
# 24-item ceiling: slots bound it — 3 rooms x 2 kinds x 4 slots.
db = SessionLocal()
try:
    n = db.query(models.MuseumItem).filter_by(user_id=2011).count()
finally:
    db.close()
assert n == 4, n
print("5. replace on occupied slot OK")

# --- 6. Remove: own only, cross-user 404. -------------------------------
r = c.delete(f"/me/museum/items/{slot0[0]['id']}", headers=ALICE)
assert r.status_code == 200 and r.json()["removed"] is True, r.text
r = c.delete(f"/me/museum/items/{slot0[0]['id']}", headers=ALICE)
assert r.status_code == 404, r.text
# Alice cannot remove Bob's item (Bob hangs one first).
r = hang(BOB, {"room": "entrance", "kind": "furniture", "slot": 0,
               "furniture_type": "lamp"})
assert r.status_code == 200, r.text
bob_lamp = r.json()["id"]
r = c.delete(f"/me/museum/items/{bob_lamp}", headers=ALICE)
assert r.status_code == 404, r.text
r = c.delete(f"/me/museum/items/{bob_lamp}", headers=BOB)
assert r.status_code == 200, r.text
mine = my_mu(ALICE)
assert len(mine["rooms"]["entrance"]) == 1, mine  # design photo only
print("6. remove (own only) OK")

# --- 7. Visibility: private, mute, block either way. --------------------
# Bob follows Alice while she is public, then she goes private:
# a follower still sees it, a stranger does not.
r = c.post("/users/2011/follow", headers=BOB)
assert r.status_code == 200, r.text
r = c.post("/me/privacy", json={"is_private": True}, headers=ALICE)
assert r.status_code == 200, r.text
assert get_mu(BOB, 2011).status_code == 200
assert get_mu(CAROL, 2011).status_code == 404
assert get_mu(ALICE, 2011).status_code == 200  # own museum always
r = c.post("/me/privacy", json={"is_private": False}, headers=ALICE)
assert r.status_code == 200, r.text
# Mute hides it for the muter only.
r = c.post("/users/2011/mute", headers=BOB)
assert r.status_code == 200 and r.json()["muted"] is True, r.text
assert get_mu(BOB, 2011).status_code == 404
assert get_mu(CAROL, 2011).status_code == 200
r = c.post("/users/2011/mute", headers=BOB)
assert r.json()["muted"] is False, r.text
# Block either way hides it.
r = c.post("/users/2012/block", headers=ALICE)
assert r.json()["blocked"] is True, r.text
assert get_mu(BOB, 2011).status_code == 404
assert get_mu(ALICE, 2012).status_code == 404
r = c.post("/users/2012/block", headers=ALICE)
assert r.json()["blocked"] is False, r.text
r = c.post("/users/2011/block", headers=BOB)
assert r.json()["blocked"] is True, r.text
assert get_mu(BOB, 2011).status_code == 404
r = c.post("/users/2011/block", headers=BOB)
assert r.json()["blocked"] is False, r.text
assert get_mu(BOB, 2011).status_code == 200
print("7. visibility (private/mute/block) OK")

# --- 8. The Official account may have a museum too. ----------------------
mk(1, "Nexora Social", "nexora")
r = hang(OFFICIAL, {"room": "entrance", "kind": "furniture", "slot": 0,
                    "furniture_type": "plant"})
assert r.status_code == 200, r.text
r = get_mu(BOB, 1)
assert r.status_code == 200, r.text
assert r.json()["rooms"]["entrance"][0]["furniture_type"] == "plant", r.text
print("8. official museum OK")

# --- 9. _media_visible: museum photos, grant-only. -----------------------
# A photo hung on Alice's wall loads for a viewer who may see
# her museum; a blocked/muted viewer falls through to the file's
# own source (a post photo still loads via its post branch).
db = SessionLocal()
try:
    assert _media_visible(db, 2012, "mu_photo_1") is True
    assert _media_visible(db, 2013, "mu_photo_1") is True
    assert _media_visible(db, 2012, "mu_unknown") is False
finally:
    db.close()
# DM photo hung on the wall: grant-only — a follower who is NOT
# a DM participant may load it while the museum shows it, and a
# stranger may not once it is taken down.
db = SessionLocal()
db.add(models.Message(sender_id=2011, recipient_id=2012, text="",
                      media_file_id="mu_dm_1", media_type="photo"))
db.commit()
db.close()
r = hang(ALICE, {"room": "family", "kind": "photo", "slot": 0,
                 "image_file_id": "mu_dm_1"})
assert r.status_code == 200, r.text
mu_dm_id = r.json()["id"]
db = SessionLocal()
try:
    assert _media_visible(db, 2012, "mu_dm_1") is True  # DM participant
    assert _media_visible(db, 2013, "mu_dm_1") is True  # museum grant
finally:
    db.close()
r = c.delete(f"/me/museum/items/{mu_dm_id}", headers=ALICE)
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 2012, "mu_dm_1") is True  # still a DM photo
    assert _media_visible(db, 2013, "mu_dm_1") is False  # grant gone
finally:
    db.close()
# Blocked viewer: the museum branch grants nothing, and the post
# branch refuses too.
r = c.post("/users/2012/block", headers=ALICE)
assert r.json()["blocked"] is True, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 2012, "mu_photo_1") is False
    assert _media_visible(db, 2013, "mu_photo_1") is True
finally:
    db.close()
r = c.post("/users/2012/block", headers=ALICE)
assert r.json()["blocked"] is False, r.text
r = c.post("/users/2011/mute", headers=BOB)
assert r.json()["muted"] is True, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 2012, "mu_photo_1") is False
    assert _media_visible(db, 2013, "mu_photo_1") is True
finally:
    db.close()
r = c.post("/users/2011/mute", headers=BOB)
assert r.json()["muted"] is False, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 2012, "mu_photo_1") is True
finally:
    db.close()
print("9. _media_visible for museum photos OK")

# --- 10. Client markers, version, routes, backup. ------------------------
JS_MARKS = ["openMuseum", "renderMuseum", "renderMuseumChips",
            "renderMuseumFallback", "buildMuseumScene", "stopMuseum",
            "muHas3D", "muFurniture", "muBuildRoom", "museumPickPhoto",
            "museumFrameTap", "museumFloorTap", "openMuseumSheet",
            "closeMuseumSheet", "museumStepRoom", "reloadMuseum",
            "museumSaveItem", "museumRemoveItem", "MUSEUM_ROOMS",
            "MUSEUM_FURNITURE", "museumItemAt", "museumRoomItems",
            "🏛️ Museum — walk through the gallery",
            "Drag on the museum canvas"]
for m in JS_MARKS:
    assert m in JS, f"missing JS marker: {m}"
assert "museum: [" in JS
# Mascot museum tips: exactly 3, no numbers anywhere in them.
import re
mm = re.search(r"  museum: \[(.*?)\],\n\};", JS, re.S)
assert mm, "mascot museum tips missing"
mu_tips = re.findall(r'"((?:[^"\\]|\\.)*)"', mm.group(1))
assert len(mu_tips) == 3, mu_tips
assert not any(ch.isdigit() for t in mu_tips for ch in t), mu_tips
# No CDN anywhere in the museum block; Three.js stays vendored.
seg = JS[JS.index("// ---------- Phase 201: Museum"):]
seg = seg[:seg.index("async function loadProfilePosts")]
assert "http" not in seg and "unpkg" not in seg, seg[:200]
# "CDN" appears exactly twice, both in comments stating there is
# no CDN ("(no CDN)" in the header, "no CDN." above muHas3D) —
# a CDN URL would contain "http", which the line above rules out.
assert seg.lower().count("cdn") == 2, seg.lower().count("cdn")
assert "(no cdn)" in seg.lower() and "no cdn." in seg.lower()
assert "vendor/three/three.min.js?v=201" in HTML
assert "MUSEUM:" in MAIN and "museum gives no points" in MAIN
for mid in ("mu-owner", "mu-room-tabs", "mu-stage", "mu-canvas",
            "mu-chips", "mu-fallback", "mu-sheet", "mu-prev", "mu-next",
            "mu-status", "mu-nogl", "mu-room-name"):
    assert f'id="{mid}"' in HTML, mid
assert '<section id="view-museum"' in HTML
assert HTML.count('class="gb-item" data-go="museum"') == 1
assert '"blood", "skills", "museum"]' in JS
assert ".mu-stage" in CSS and ".mu-tab" in CSS and ".mu-chip" in CSS
assert ".mu-fb-card" in CSS and ".mu-sheet" in CSS and ".mu-owner" in CSS
assert HTML.count("?v=201") == 10, HTML.count("?v=201")
assert "?v=20" + "0" not in HTML
assert "app.js?v=201" in HTML and "games.js?v=201" in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert 'menu_url.rstrip("/") + "/?v=201"' in BOT
assert ("/?v=20" + "0") not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 193, len(paths)
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
print("10. client + version + routes + backup OK")

print("PHASE 201 SERVER OK")

# --- 11. Node harness: real app.js, tracked DOM, THREE stub. --------------
APP_PRELUDE = r'''
// Phase-201 app harness: run the real app.js with window.Telegram
// MISSING (the Phase-188 boot-proof setup), a TRACKED byId
// registry, a fetch stub routed per path, and a minimal THREE
// stub (same shape as the Phase-196 game stub) so the museum's
// 3D scene can build without WebGL.
function makeEl201(tag) {
  const el = {
    tag: tag || "div", children: [], parent: null, hidden: false,
    id: "", className: "", textContent: "", value: "", type: "",
    checked: false, disabled: false, maxLength: 0, placeholder: "",
    rows: 0, src: "", href: "", alt: "", loading: "", title: "",
    onclick: null, onchange: null,
    clientWidth: 360, clientHeight: 640, scrollWidth: 0,
    scrollHeight: 0, scrollTop: 0, offsetWidth: 50, offsetHeight: 40,
    style: { setProperty(k, v) { this[k] = v; }, removeProperty() {}, getPropertyValue() { return ""; } },
    dataset: {},
    _cls: new Set(),
    classList: { add(...c) { c.forEach(x => el._cls.add(x)); },
      remove(...c) { c.forEach(x => el._cls.delete(x)); },
      toggle(c, f) { if (f === undefined) f = !el._cls.has(c); if (f) el._cls.add(c); else el._cls.delete(c); return f; },
      contains(x) { return el._cls.has(x); } },
    _handlers: {},
    addEventListener(t, fn) { (el._handlers[t] = el._handlers[t] || []).push(fn); },
    removeEventListener(t, fn) { const h = el._handlers[t] || []; const i = h.indexOf(fn); if (i >= 0) h.splice(i, 1); },
    _fire(t, ev) { (el._handlers[t] || []).forEach(fn => fn(ev || {})); },
    focus() {}, click() {}, scrollIntoView() {},
    setAttribute(k, v) { el[k] = v; },
    getAttribute(k) { return el[k] !== undefined ? el[k] : null; },
    getContext() { return null; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 50, height: 40, right: 50, bottom: 40 }; },
    append(...kids) { for (const k of kids) { if (k) { k.parent = el; el.children.push(k); } } },
    appendChild(k) { k.parent = el; el.children.push(k); return k; },
    prepend(...kids) { for (let i = kids.length - 1; i >= 0; i--) { kids[i].parent = el; el.children.unshift(kids[i]); } },
    insertBefore(node, ref) { node.parent = el; const i = ref ? el.children.indexOf(ref) : -1; if (i >= 0) el.children.splice(i, 0, node); else el.children.push(node); return node; },
    remove() { if (el.parent) { const i = el.parent.children.indexOf(el); if (i >= 0) el.parent.children.splice(i, 1); el.parent = null; } },
    querySelectorAll(sel) {
      const out = [];
      const walk = (node) => {
        for (const ch of node.children) {
          if (sel.charAt(0) === ".") {
            if ((ch.className || "").split(" ").indexOf(sel.slice(1)) >= 0) out.push(ch);
          } else if (sel.charAt(0) !== "[") {
            if (ch.tag === sel) out.push(ch);
          }
          walk(ch);
        }
      };
      walk(this);
      return out;
    },
    querySelector(sel) { const r = this.querySelectorAll(sel); return r.length ? r[0] : null; },
  };
  Object.defineProperty(el, "firstChild", { get() { return el.children[0] || null; } });
  Object.defineProperty(el, "innerHTML", { get() { return el._html || ""; }, set(v) { el._html = String(v); el.children = []; }, configurable: true });
  return el;
}
const __body201 = makeEl201("body");
const __docEl201 = makeEl201("html");
global.window = {
  location: { search: "", hash: "", reload() {} },
  open() {}, Telegram: undefined,
  devicePixelRatio: 1, innerWidth: 360, innerHeight: 740,
  addEventListener() {}, removeEventListener() {}, scrollTo() {},
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  WebGLRenderingContext: function () {},
};
global.document = {
  _byId: {},
  getElementById(id) { if (!this._byId[id]) { const e = makeEl201("div"); e.id = id; this._byId[id] = e; } return this._byId[id]; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(t) { return makeEl201(t); },
  createTextNode(text) { const n = makeEl201("#text"); n.textContent = text; return n; },
  addEventListener() {}, removeEventListener() {},
  body: __body201, documentElement: __docEl201, title: "", hidden: false,
};
const _store201 = new Map();
global.localStorage = { getItem: (k) => _store201.has(k) ? _store201.get(k) : null, setItem: (k, v) => _store201.set(k, String(v)), removeItem: (k) => _store201.delete(k) };
global.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.navigator = {};
global.location = global.window.location;
global.alert = () => {}; global.confirm = () => false;
global.getComputedStyle = (el) => ({ fontSize: "16px", getPropertyValue: () => "" });
global.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 16);
global.cancelAnimationFrame = (id) => clearTimeout(id);
global.IntersectionObserver = class { constructor() {} observe() {} unobserve() {} disconnect() {} };
global.ResizeObserver = class { constructor() {} observe() {} unobserve() {} disconnect() {} };
global.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
global.window.matchMedia = global.matchMedia;
process.on("uncaughtException", (e) => { console.log("UNCAUGHT: " + (e && e.message)); process.exit(2); });
process.on("unhandledRejection", (e) => { console.log("UNHANDLED_REJECTION: " + (e && e.message)); process.exit(2); });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
function assert(c, msg) { if (!c) throw new Error("ASSERT FAILED: " + msg); }
function findByClass(el, cls, out) {
  out = out || [];
  if ((el.className || "").split(" ").indexOf(cls) >= 0) out.push(el);
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
// --- minimal THREE stub (same shape as the Phase-196 game stub) ---
function muMkNode() {
  const n = { children: [], parent: null,
    position: { x: 0, y: 0, z: 0, set(x, y, z) { this.x = x; this.y = y; this.z = z; } },
    rotation: { x: 0, y: 0, z: 0, order: "" },
    add(c) { c.parent = n; n.children.push(c); return n; },
    remove(c) { const i = n.children.indexOf(c); if (i >= 0) n.children.splice(i, 1); },
    traverse(fn) { fn(n); for (const ch of n.children.slice()) { if (ch.traverse) ch.traverse(fn); else fn(ch); } },
    lookAt() {}, updateProjectionMatrix() {} };
  return n;
}
const created201 = { meshes: [], renderers: [], textures: [], renderCalls: 0, disposeCalls: 0 };
function mkGeo201(kind, args) { const g = { kind, args, disposed: false, dispose() { g.disposed = true; } }; return g; }
function mkMat201(kind, params) { const m = { kind, params: params || {}, map: (params && params.map) || null, disposed: false, dispose() { m.disposed = true; } }; return m; }
global.THREE = global.window.THREE = {
  DoubleSide: "double",
  Color: function (c) { this.c = c; },
  Fog: function (c, n, f) { this.c = c; this.near = n; this.far = f; },
  Scene: function () { const s = muMkNode(); s.background = null; s.fog = null; return s; },
  PerspectiveCamera: function (fov, aspect, near, far) {
    const c = muMkNode();
    c.fov = fov; c.aspect = aspect; c.near = near; c.far = far;
    return c;
  },
  WebGLRenderer: function (opts) {
    const r = { domElement: opts.canvas, renderCalls: 0, disposed: false,
      setPixelRatio() {}, setSize() {},
      render() { r.renderCalls++; created201.renderCalls++; },
      dispose() { r.disposed = true; created201.disposeCalls++; } };
    created201.renderers.push(r);
    return r;
  },
  HemisphereLight: function () { return muMkNode(); },
  PointLight: function () { return muMkNode(); },
  Mesh: function (geo, mat) { const m = muMkNode(); m.geometry = geo; m.material = mat; created201.meshes.push(m); return m; },
  Group: function () { return muMkNode(); },
  BoxGeometry: function (...a) { return mkGeo201("box", a); },
  PlaneGeometry: function (...a) { return mkGeo201("plane", a); },
  CylinderGeometry: function (...a) { return mkGeo201("cylinder", a); },
  ConeGeometry: function (...a) { return mkGeo201("cone", a); },
  SphereGeometry: function (...a) { return mkGeo201("sphere", a); },
  IcosahedronGeometry: function (...a) { return mkGeo201("icosahedron", a); },
  CircleGeometry: function (...a) { return mkGeo201("circle", a); },
  MeshStandardMaterial: function (p) { return mkMat201("standard", p); },
  MeshBasicMaterial: function (p) { return mkMat201("basic", p); },
  TextureLoader: function () { return { load(url) { const t = { url, disposed: false, dispose() { t.disposed = true; } }; created201.textures.push(t); return t; } }; },
};
// --- stubbed server state: Alice (me) views Bob's museum; then me
// becomes Bob for the owner-mode checks.
let HARNESS_ME = { telegram_id: 2011, first_name: "Alice", username: "alice",
  is_admin: false, photo_file_id: null, media_token: "" };
const MU_BOB = { user_id: 2012, first_name: "Bob", username: "bob",
  photo_file_id: null, is_verified: true,
  rooms: { entrance: [{ id: 1, room: "entrance", kind: "photo", slot: 0,
             image_file_id: "mu_photo_1", ref_kind: "post", ref_id: 11,
             furniture_type: null }],
           lounge: [{ id: 2, room: "lounge", kind: "furniture", slot: 1,
             image_file_id: null, ref_kind: null, ref_id: null,
             furniture_type: "sofa" }],
           family: [] } };
const MU_EMPTY = { user_id: 2011, first_name: "Alice", username: "alice",
  photo_file_id: null, is_verified: false,
  rooms: { entrance: [], lounge: [], family: [] } };
const USER_BOB = { telegram_id: 2012, first_name: "Bob", username: "bob",
  photo_file_id: null, cover_file_id: null, bio: "Bob bio", followers: 5,
  following_count: 2, following: false, has_pending_request: false,
  blocked_by_me: false, muted_by_me: false, is_private: false,
  is_official: false, is_verified: true, portfolio_enabled: false,
  blood_group: null, skills: { teach: [], learn: [] }, name_locked_days: 0 };
global.fetch = async (url, opts) => {
  const path = String(url).split("?")[0];
  let data = {};
  if (path === "/auth") data = HARNESS_ME;
  else if (path === "/users/2012") data = USER_BOB;
  else if (path === "/users/2012/museum") data = MU_BOB;
  else if (path === "/me/museum") data = HARNESS_ME.telegram_id === 2012 ? MU_BOB : MU_EMPTY;
  else if (path === "/highlights/user/2012") data = { highlights: [] };
  else if (path === "/users/2012/posts") data = { posts: [{ id: 11, type: "photo", caption: "Wall", media_file_id: "mu_photo_1" }], next_cursor: null };
  else if (path === "/users/2011/posts") data = { posts: [], next_cursor: null };
  else if (path === "/feed") data = { posts: [], next_cursor: null };
  else if (path === "/designs") data = { designs: [] };
  return { ok: true, status: 200, json: async () => data, text: async () => "" };
};
'''

APP_MAIN = r'''
try {
  eval(APP_SRC_201 + "\n;globalThis.__nx201 = { getMe: () => me, setMe: (v) => { me = v; HARNESS_ME = v; }, openMuseum, openProfile, stopMuseum, buildMuseumScene, muHas3D, museumItemAt, museumRoomItems, getMu: () => ({ owner: museumOwnerId, room: museumRoom, isOwner: museumIsOwner, data: museumData, yaw: () => muYaw, pitch: () => muPitch, scene: () => muScene }) };");
  console.log("EVAL_OK: app.js parsed and top-level ran without throwing");
} catch (e) { console.log("EVAL_THROW: " + (e && e.message)); process.exit(3); }
(async () => {
  await sleep(50);
  assert(__nx201.getMe() && __nx201.getMe().telegram_id === 2011, "boot sets me (Alice)");
  assert(__nx201.muHas3D(), "THREE stub present");
  // The 3D mascot (Phase 156) may already own a renderer from
  // boot, so the museum counts below are RELATIVE to this point.
  const rend0 = created201.renderers.length;
  const tex0 = created201.textures.length;
  const disp0 = created201.disposeCalls;
  // 1. Visitor (Alice) opens Bob's museum.
  await __nx201.openMuseum(2012);
  const mu = __nx201.getMu();
  assert(mu.owner === 2012 && mu.room === "entrance" && mu.isOwner === false, "visitor state");
  assert(mu.data && mu.data.first_name === "Bob", "museum data loaded");
  const ownerEl = document.getElementById("mu-owner");
  assert(visibleText(ownerEl).indexOf("Bob") >= 0, "owner line names Bob");
  assert(findByClass(ownerEl, "vname").length === 1, "owner line uses .vname");
  assert(findByClass(ownerEl, "vname-text").length === 1, "owner line uses .vname-text");
  const tabs = document.getElementById("mu-room-tabs");
  assert(findByClass(tabs, "mu-tab").length === 3, "3 room tabs");
  const chips = document.getElementById("mu-chips");
  const chipBtns = findByClass(chips, "mu-chip");
  assert(chipBtns.length === 8, "8 chips (4 frames + 4 floor), got " + chipBtns.length);
  let frameImg = null;
  for (const ch of chipBtns[0].children) if (ch.tag === "img") frameImg = ch;
  assert(frameImg && frameImg.src.indexOf("mu_photo_1") >= 0, "frame 0 shows the hung photo");
  assert(visibleText(chips).indexOf("Hang a photo") < 0, "visitor sees no hang affordance");
  assert(visibleText(chips).indexOf("Empty frame") >= 0, "visitor sees Empty frame");
  // 3D scene built with the stub renderer.
  const sc = __nx201.getMu().scene();
  assert(sc && sc.renderer, "renderer created");
  assert(created201.renderers.length === rend0 + 1, "one museum renderer");
  assert(sc.roomGroup && sc.roomGroup.children.length >= 7,
    "room group has floor+walls+frames, got " + (sc.roomGroup && sc.roomGroup.children.length));
  assert(created201.textures.length === tex0 + 1 &&
    created201.textures[created201.textures.length - 1].url.indexOf("mu_photo_1") >= 0,
    "photo texture loaded for the hung frame");
  // 2. Drag to look changes the yaw; the loop applies it to the camera.
  const cv = document.getElementById("mu-canvas");
  cv._fire("pointerdown", { clientX: 100, clientY: 100 });
  cv._fire("pointermove", { clientX: 130, clientY: 100 });
  cv._fire("pointerup", {});
  assert(Math.abs(__nx201.getMu().yaw() + 0.15) < 1e-9, "drag 30px -> yaw -0.15, got " + __nx201.getMu().yaw());
  await sleep(60);
  assert(Math.abs(sc.camera.rotation.y - __nx201.getMu().yaw()) < 1e-9, "loop applies yaw to camera");
  assert(created201.renderCalls > 0, "loop renders");
  // 3. Visitor taps the occupied frame: view-only sheet.
  const frame0 = findByClass(chips, "mu-chip")[0];
  frame0.onclick();
  const sheet = document.getElementById("mu-sheet");
  assert(sheet.hidden === false, "sheet opens");
  assert(findBtn(sheet, "View photo"), "visitor sheet has View photo");
  assert(!findBtn(sheet, "Replace photo"), "visitor sheet has no Replace photo");
  assert(!findBtn(sheet, "Remove from wall"), "visitor sheet has no Remove");
  const closeBtn = findBtn(sheet, "✕");
  assert(closeBtn, "sheet close button");
  closeBtn.onclick();
  assert(sheet.hidden === true, "sheet closes");
  // 4. Room switch rebuilds the room and shows the sofa.
  const loungeTab = findBtn(tabs, "Lounge");
  assert(loungeTab, "Lounge tab");
  loungeTab.onclick();
  assert(__nx201.getMu().room === "lounge", "room switches to lounge");
  assert(visibleText(chips).indexOf("Sofa") >= 0, "lounge chips show the sofa");
  const sc2 = __nx201.getMu().scene();
  assert(sc2 === sc, "same renderer across rooms");
  // 5. No-THREE fallback: hide THREE, reopen, flat grid appears.
  const savedTHREE = global.THREE;
  global.THREE = undefined;
  global.window.THREE = undefined;
  assert(!__nx201.muHas3D(), "muHas3D false without THREE");
  await __nx201.openMuseum(2012);
  const fb = document.getElementById("mu-fallback");
  assert(fb.hidden === false, "fallback shown without THREE");
  assert(document.getElementById("mu-stage").hidden === true, "stage hidden without THREE");
  assert(findByClass(fb, "mu-fb-card").length === 8, "fallback has 8 cards");
  assert(document.getElementById("mu-nogl").hidden === false, "no-WebGL hint shown");
  global.THREE = savedTHREE;
  global.window.THREE = savedTHREE;
  assert(__nx201.muHas3D(), "muHas3D true again");
  await __nx201.openMuseum(2012);
  assert(created201.renderers.length === rend0 + 2, "renderer rebuilt after fallback");
  assert(document.getElementById("mu-fallback").hidden === true, "fallback hidden again");
  // 6. Owner mode: me becomes Bob; hang affordances + catalog appear.
  __nx201.setMe({ telegram_id: 2012, first_name: "Bob", username: "bob",
    is_admin: false, photo_file_id: null, media_token: "" });
  await __nx201.openMuseum(2012);
  assert(__nx201.getMu().isOwner === true, "owner state");
  assert(visibleText(chips).indexOf("Hang a photo") >= 0, "owner sees Hang a photo");
  const emptyFrame = findByClass(chips, "mu-chip")[1];
  emptyFrame.onclick();
  assert(sheet.hidden === false, "owner frame sheet opens");
  assert(visibleText(sheet).indexOf("From one of my posts") >= 0, "frame sheet has post picker");
  assert(!findBtn(sheet, "Replace photo"), "empty frame has no Replace photo");
  assert(!findBtn(sheet, "Remove from wall"), "empty frame has no Remove");
  findBtn(sheet, "✕").onclick();
  const occupied = findByClass(chips, "mu-chip")[0];
  occupied.onclick();
  assert(findBtn(sheet, "View photo"), "owner frame sheet also views");
  assert(findBtn(sheet, "Replace photo"), "owner frame sheet has Replace photo");
  assert(findBtn(sheet, "Remove from wall"), "owner frame sheet has Remove");
  findBtn(sheet, "✕").onclick();
  // Empty floor spot: furniture catalog with all six types.
  const loungeTab2 = findBtn(tabs, "Lounge");
  loungeTab2.onclick();
  const emptyFloor = findByClass(chips, "mu-chip")[4];
  emptyFloor.onclick();
  assert(sheet.hidden === false, "owner floor sheet opens");
  for (const label of ["🪑 Chair", "🛋️ Sofa", "🪴 Plant", "🪵 Table", "💡 Lamp", "🟫 Rug"])
    assert(findBtn(sheet, label), "catalog row " + label);
  findBtn(sheet, "✕").onclick();
  // 7. Profile page carries the Museum button.
  __nx201.setMe({ telegram_id: 2011, first_name: "Alice", username: "alice",
    is_admin: false, photo_file_id: null, media_token: "" });
  await __nx201.openProfile(2012);
  const box = document.getElementById("profile-box");
  const muBtn = findBtn(box, "🏛️ Museum — walk through the gallery");
  assert(muBtn, "profile Museum button");
  // 8. stopMuseum disposes the renderer and clears the scene.
  __nx201.stopMuseum();
  assert(__nx201.getMu().scene() === null, "scene cleared");
  // Two disposes: one in the no-THREE fallback's stopMuseum, one here.
  assert(created201.disposeCalls === disp0 + 2, "renderer disposed, got " + created201.disposeCalls);
  console.log("APP HARNESS OK (phase-201: visitor view + drag + rooms + fallback + owner sheets + profile button)");
  process.exit(0);
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_app_harness():
    src = open(os.path.join(ROOT, "code/webapp/app.js")).read()
    harness = (APP_PRELUDE
               + "\nconst APP_SRC_201 = " + json.dumps(src) + ";\n"
               + APP_MAIN)
    path = "/tmp/t201_app_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "EVAL_OK" in r.stdout, (r.stdout, r.stderr)
    assert "APP HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("app node harness OK (visitor view + drag + rooms + fallback + "
          "owner sheets + profile button)")


_run_app_harness()
print("PHASE 201 OK")
