"""Phase 199 tests: Portfolio (owner pick: sample #1 Organic Clay).

One portfolio per member (about, role, cover photo, enabled flag)
+ work samples (post / design / project). Invisible everywhere
until the owner turns it on in Settings; the profile then shows
a Profile/Portfolio dropdown, defaulting to Profile. Visibility
reuses the Phase 136/174 rules (private, block either way, mute).
No points, no payments. Plain script (run.sh runs it with python
directly).
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase199.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _media_visible  # noqa: E402
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


ALICE = H(1991, "Alice", "alice")
BOB = H(1992, "Bob", "bob")
CAROL = H(1993, "Carol", "carol")
DAVE = H(1994, "Dave", "dave")
OFFICIAL = H(1, "Nexora Social", "nexora")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()

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


for uid, name, uname in ((1991, "Alice", "alice"), (1992, "Bob", "bob"),
                         (1993, "Carol", "carol"), (1994, "Dave", "dave")):
    mk(uid, name, uname)


def mkpost(headers, caption, photo=None):
    body = {"type": "photo" if photo else "text", "caption": caption}
    if photo:
        body["media_file_id"] = photo
    r = c.post("/posts", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def get_pf(headers, uid):
    r = c.get(f"/users/{uid}/portfolio", headers=headers)
    return r


def my_pf(headers):
    r = c.get("/me/portfolio", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- 1. Default OFF: hidden everywhere, no dropdown. ---------------------
r = get_pf(BOB, 1991)
assert r.status_code == 404, r.text
r = c.get("/users/1991", headers=BOB)
assert r.status_code == 200, r.text
assert r.json()["portfolio_enabled"] is False, r.text
mine = my_pf(ALICE)
assert mine == {"user_id": 1991, "first_name": "Alice", "username": "alice",
                "photo_file_id": None, "is_verified": False, "about": "",
                "role": "", "cover_file_id": None, "enabled": False,
                "items": []}, mine
print("1. default OFF + hidden OK")

# --- 2. Save + validation: banned words, foreign cover. ------------------
db = SessionLocal()
if not db.query(models.BannedWord).filter_by(word="zqxjword").first():
    db.add(models.BannedWord(word="zqxjword", added_by=999))
    db.commit()
db.close()
r = c.post("/me/portfolio", json={"about": "I love zqxjword things",
                                  "role": "", "enabled": True},
           headers=ALICE)
assert r.status_code == 400, r.text
r = c.post("/me/portfolio", json={"about": "About Alice",
                                  "role": "Designer",
                                  "cover_file_id": "someone_elses_photo",
                                  "enabled": True}, headers=ALICE)
assert r.status_code == 400, r.text
p_photo = mkpost(ALICE, "Poster work", photo="pf_photo_1")
r = c.post("/me/portfolio", json={"about": "About Alice",
                                  "role": "Graphic Designer & Photographer",
                                  "cover_file_id": "pf_photo_1",
                                  "enabled": True}, headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["enabled"] is True, r.text
assert r.json()["cover_file_id"] == "pf_photo_1", r.text
r = c.get("/users/1991", headers=BOB)
assert r.json()["portfolio_enabled"] is True, r.text
r = get_pf(BOB, 1991)
assert r.status_code == 200, r.text
assert r.json()["about"] == "About Alice", r.text
assert r.json()["role"] == "Graphic Designer & Photographer", r.text
assert r.json()["items"] == [], r.text
print("2. save + validation OK")

# --- 3. Work items: post / design / project + bad inputs. ----------------
p_text = mkpost(ALICE, "Just words")
r = c.post("/me/portfolio/items",
           json={"kind": "post", "ref_id": p_text}, headers=ALICE)
assert r.status_code == 400, r.text  # a text post has no photo
r = c.post("/me/portfolio/items",
           json={"kind": "post", "ref_id": p_photo}, headers=ALICE)
assert r.status_code == 200, r.text
i_post = r.json()
assert i_post["kind"] == "post" and i_post["ref_id"] == p_photo, r.text
assert i_post["image_file_id"] == "pf_photo_1", r.text
assert i_post["title"] == "Poster work", r.text  # auto from caption
db = SessionLocal()
db.add(models.Design(image_file_id="pf_design_1", prompt="Logo mark"))
db.commit()
design_id = db.query(models.Design).filter_by(
    image_file_id="pf_design_1").first().id
db.close()
r = c.post("/me/portfolio/items",
           json={"kind": "design", "ref_id": design_id}, headers=ALICE)
assert r.status_code == 200, r.text
i_design = r.json()
assert i_design["image_file_id"] == "pf_design_1", r.text
assert i_design["title"] == "Logo mark", r.text
r = c.post("/me/portfolio/items",
           json={"kind": "project", "title": "Brand Book",
                 "image_file_id": "pf_photo_1"}, headers=ALICE)
assert r.status_code == 200, r.text
i_proj = r.json()
assert i_proj["kind"] == "project" and i_proj["title"] == "Brand Book"
r = c.post("/me/portfolio/items",
           json={"kind": "project", "title": "",
                 "image_file_id": "pf_photo_1"}, headers=ALICE)
assert r.status_code == 400, r.text  # project needs a title
r = c.post("/me/portfolio/items",
           json={"kind": "project", "title": "X",
                 "image_file_id": "not_mine"}, headers=ALICE)
assert r.status_code == 400, r.text  # project photo must be my own
r = c.post("/me/portfolio/items",
           json={"kind": "design", "ref_id": 999999}, headers=ALICE)
assert r.status_code == 404, r.text
r = c.post("/me/portfolio/items",
           json={"kind": "video", "ref_id": p_photo}, headers=ALICE)
assert r.status_code == 400, r.text
p_bob = mkpost(BOB, "Bob's photo", photo="pf_bob_1")
r = c.post("/me/portfolio/items",
           json={"kind": "post", "ref_id": p_bob}, headers=ALICE)
assert r.status_code == 404, r.text  # someone else's post
items = my_pf(ALICE)["items"]
assert [i["id"] for i in items] == [i_post["id"], i_design["id"],
                                    i_proj["id"]], items
print("3. work items + bad inputs OK")

# --- 4. Reorder + remove. -------------------------------------------------
r = c.post("/me/portfolio/items/reorder",
           json={"item_ids": [i_proj["id"], i_post["id"], i_design["id"]]},
           headers=ALICE)
assert r.status_code == 200, r.text
assert r.json() == {"reordered": True, "count": 3}, r.text
items = my_pf(ALICE)["items"]
assert [i["id"] for i in items] == [i_proj["id"], i_post["id"],
                                    i_design["id"]], items
r = c.post("/me/portfolio/items/reorder",
           json={"item_ids": [i_post["id"], i_design["id"]]},
           headers=ALICE)
assert r.status_code == 400, r.text  # missing one
r = c.post("/me/portfolio/items/reorder",
           json={"item_ids": [i_post["id"], i_post["id"], i_design["id"],
                              i_proj["id"]]}, headers=ALICE)
assert r.status_code == 400, r.text  # duplicate
r = c.delete(f"/me/portfolio/items/{i_design['id']}", headers=BOB)
assert r.status_code == 404, r.text  # not mine to remove
r = c.delete(f"/me/portfolio/items/{i_design['id']}", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json() == {"removed": True}, r.text
r = c.delete(f"/me/portfolio/items/{i_design['id']}", headers=ALICE)
assert r.status_code == 404, r.text
items = my_pf(ALICE)["items"]
assert [i["id"] for i in items] == [i_proj["id"], i_post["id"]], items
print("4. reorder + remove OK")

# --- 5. Cap: 20 work samples (Dave, fresh). -------------------------------
mkpost(DAVE, "Dave photo", photo="pf_dave_1")
for i in range(20):
    r = c.post("/me/portfolio/items",
               json={"kind": "project", "title": f"Dave {i}",
                     "image_file_id": "pf_dave_1"}, headers=DAVE)
    assert r.status_code == 200, r.text
r = c.post("/me/portfolio/items",
           json={"kind": "project", "title": "Dave 21",
                 "image_file_id": "pf_dave_1"}, headers=DAVE)
assert r.status_code == 400, r.text
print("5. 20-item cap OK")

# --- 6. Visibility: toggle off, private, block, mute. ---------------------
r = c.post("/me/portfolio", json={"about": "About Alice",
                                  "role": "Designer",
                                  "cover_file_id": "pf_photo_1",
                                  "enabled": False}, headers=ALICE)
assert r.status_code == 200, r.text
assert get_pf(BOB, 1991).status_code == 404
r = c.post("/me/portfolio", json={"about": "About Alice",
                                  "role": "Designer",
                                  "cover_file_id": "pf_photo_1",
                                  "enabled": True}, headers=ALICE)
assert r.status_code == 200, r.text
assert get_pf(BOB, 1991).status_code == 200
# Private: a follower still sees it, a stranger does not.
r = c.post("/users/1991/follow", headers=BOB)
assert r.status_code == 200, r.text
r = c.post("/me/privacy", json={"is_private": True}, headers=ALICE)
assert r.status_code == 200, r.text
assert get_pf(BOB, 1991).status_code == 200
assert get_pf(CAROL, 1991).status_code == 404
r = c.post("/me/privacy", json={"is_private": False}, headers=ALICE)
assert r.status_code == 200, r.text
assert get_pf(CAROL, 1991).status_code == 200
# Block either way hides it.
r = c.post("/users/1992/block", headers=ALICE)
assert r.status_code == 200 and r.json()["blocked"] is True, r.text
assert get_pf(BOB, 1991).status_code == 404
r = c.post("/users/1992/block", headers=ALICE)
assert r.json()["blocked"] is False, r.text
assert get_pf(BOB, 1991).status_code == 200
r = c.post("/users/1991/block", headers=BOB)
assert r.json()["blocked"] is True, r.text
assert get_pf(BOB, 1991).status_code == 404
r = c.post("/users/1991/block", headers=BOB)
assert r.json()["blocked"] is False, r.text
# Mute hides it for the muter only.
r = c.post("/users/1991/mute", headers=BOB)
assert r.status_code == 200 and r.json()["muted"] is True, r.text
assert get_pf(BOB, 1991).status_code == 404
assert get_pf(CAROL, 1991).status_code == 200
r = c.post("/users/1991/mute", headers=BOB)
assert r.json()["muted"] is False, r.text
assert get_pf(BOB, 1991).status_code == 200
print("6. visibility (toggle/private/block/mute) OK")

# --- 7. A deleted post's item drops out of the view. ----------------------
r = c.delete(f"/posts/{p_photo}", headers=ALICE)
assert r.status_code == 200, r.text
items = get_pf(BOB, 1991).json()["items"]
assert [i["id"] for i in items] == [i_proj["id"]], items
print("7. deleted-post item drops out OK")

# --- 8. The Official account may have a portfolio too. --------------------
mk(1, "Nexora Social", "nexora")
r = c.post("/me/portfolio", json={"about": "Official showcase",
                                  "role": "Nexora Social",
                                  "enabled": True}, headers=OFFICIAL)
assert r.status_code == 200, r.text
r = get_pf(BOB, 1)
assert r.status_code == 200, r.text
assert r.json()["about"] == "Official showcase", r.text
print("8. official portfolio OK")

# --- 9. _media_visible: a DM photo used as a cover. -----------------------
# Grant-only: the portfolio branch lets a viewer who may see the
# portfolio load the cover, and otherwise falls through — a DM
# participant still loads the DM photo in the thread even with
# the portfolio off, and a blocked/muted viewer still hits the
# post branch's own checks for a post-photo cover.
db = SessionLocal()
db.add(models.Message(sender_id=1991, recipient_id=1992, text="",
                      media_file_id="pf_dm_1", media_type="photo"))
db.commit()
db.close()
r = c.post("/me/portfolio", json={"about": "About Alice",
                                  "role": "Designer",
                                  "cover_file_id": "pf_dm_1",
                                  "enabled": True}, headers=ALICE)
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 1992, "pf_dm_1") is True
    assert _media_visible(db, 1993, "pf_dm_1") is True
    assert _media_visible(db, 1992, "pf_unknown") is False
finally:
    db.close()
r = c.post("/me/portfolio", json={"about": "About Alice",
                                  "role": "Designer",
                                  "cover_file_id": "pf_dm_1",
                                  "enabled": False}, headers=ALICE)
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    # Portfolio off: Bob still loads it (DM participant), Carol
    # does not (stranger, no other source grants it).
    assert _media_visible(db, 1992, "pf_dm_1") is True
    assert _media_visible(db, 1993, "pf_dm_1") is False
finally:
    db.close()
p_photo2 = mkpost(ALICE, "Second poster", photo="pf_photo_2")
r = c.post("/me/portfolio", json={"about": "About Alice",
                                  "role": "Designer",
                                  "cover_file_id": "pf_photo_2",
                                  "enabled": True}, headers=ALICE)
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 1992, "pf_photo_2") is True
    assert _media_visible(db, 1993, "pf_photo_2") is True
finally:
    db.close()
r = c.post("/users/1992/block", headers=ALICE)
assert r.json()["blocked"] is True, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 1992, "pf_photo_2") is False
    assert _media_visible(db, 1993, "pf_photo_2") is True
finally:
    db.close()
r = c.post("/users/1992/block", headers=ALICE)
assert r.json()["blocked"] is False, r.text
r = c.post("/users/1991/mute", headers=BOB)
assert r.json()["muted"] is True, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 1992, "pf_photo_2") is False
    assert _media_visible(db, 1993, "pf_photo_2") is True
finally:
    db.close()
r = c.post("/users/1991/mute", headers=BOB)
assert r.json()["muted"] is False, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 1992, "pf_photo_2") is True
finally:
    db.close()
print("9. _media_visible for portfolio cover OK")

# --- 10. Client markers, version, routes, backup. -------------------------
JS_MARKS = ["portfolioDropdownEl", "renderPortfolioTab",
            "openPortfolioEditor", "/me/portfolio/cover/upload",
            "/me/portfolio/items/upload",
            "settingsPortfolio", "Profile/Portfolio",
            "Show my portfolio", "Edit portfolio",
            "pf-cover", "pf-shade", "pf-work-grid", "pf-dd-menu",
            "profileTab", "profileUser", "openSettingsDetail(\"portfolio\")",
            "settingsHubRow(\"🖼️\", \"Portfolio\""]
for m in JS_MARKS:
    assert m in JS, f"missing JS marker: {m}"
# Phase 204: the pickers are gone — cover + work come fresh
# from the phone gallery now.
for m in ("async function portfolioPickPhotos",
          "async function portfolioPickPosts",
          "async function portfolioPickDesigns",
          "portfolioPickPhotos(", "portfolioPickPosts(",
          "portfolioPickDesigns(", "Choose cover photo",
          "Choose one of my posts", "Choose a design",
          "Choose a photo", "From one of my posts",
          "From the Design gallery", "Project (my own photo)"):
    assert m not in JS, f"removed picker marker still present: {m}"
assert '(currentTab === "portfolio" ? "Portfolio" : "Profile") + " ▾"' in JS
assert "pf-cover" in CSS and ".pf-shade" in CSS and ".pf-work-grid" in CSS
assert ".pf-dd-menu" in CSS and ".pf-edit-row" in CSS
assert ".pf-work-card" in CSS and ".pf-picker" in CSS
assert HTML.count("?v=204") == 10, HTML.count("?v=204")
assert "?v=20" + "0" not in HTML
assert "app.js?v=204" in HTML and "games.js?v=204" in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert "/?v=204" in BOT and "/?v=19" + "8" not in BOT
paths = set()
for route in app.routes:
    paths.add(route.path)
assert len(paths) == 191, len(paths)
for want in ("/users/{telegram_id}/portfolio", "/me/portfolio",
             "/me/portfolio/items",
             "/me/portfolio/items/{item_id}",
             "/me/portfolio/items/reorder"):
    assert want in paths, want
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
print("10. client + version + routes + backup OK")

print("PHASE 199 SERVER OK")

# --- 11. Node harness: real app.js, tracked DOM, routed fetch. ------------
APP_PRELUDE = r'''
// Phase-199 app harness: run the real app.js with window.Telegram
// MISSING (the Phase-188 boot-proof setup), a TRACKED byId
// registry, and a fetch stub routed per path. The DOM stub's
// querySelectorAll searches descendants by class/tag and an
// innerHTML assignment clears children — openProfile and
// renderPortfolioTab both rely on those two behaviours.
function makeEl199(tag) {
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
const __body199 = makeEl199("body");
const __docEl199 = makeEl199("html");
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
  getElementById(id) { if (!this._byId[id]) { const e = makeEl199("div"); e.id = id; this._byId[id] = e; } return this._byId[id]; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(t) { return makeEl199(t); },
  createTextNode(text) { const n = makeEl199("#text"); n.textContent = text; return n; },
  addEventListener() {}, removeEventListener() {},
  body: __body199, documentElement: __docEl199, title: "", hidden: false,
};
const _store199 = new Map();
global.localStorage = { getItem: (k) => _store199.has(k) ? _store199.get(k) : null, setItem: (k, v) => _store199.set(k, String(v)), removeItem: (k) => _store199.delete(k) };
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
// --- stubbed server state: Alice (me) views Bob (portfolio ON)
// and Carol (portfolio OFF); then me becomes Bob for the editor.
let HARNESS_ME = { telegram_id: 1991, first_name: "Alice", username: "alice",
  is_admin: false, photo_file_id: null, media_token: "" };
const PF_BOB = { user_id: 1992, first_name: "Bob", username: "bob",
  photo_file_id: null, is_verified: false, about: "About Bob",
  role: "Designer", cover_file_id: "pf_cover_1", enabled: true,
  items: [{ id: 1, kind: "post", title: "Poster", image_file_id: "pf_photo_1" },
          { id: 2, kind: "design", title: "Logo", image_file_id: "pf_design_1" }] };
const USER_BOB = { telegram_id: 1992, first_name: "Bob", username: "bob",
  photo_file_id: null, cover_file_id: null, bio: "Bob bio", followers: 5,
  following_count: 2, following: false, has_pending_request: false,
  blocked_by_me: false, muted_by_me: false, is_private: false,
  is_official: false, is_verified: false, portfolio_enabled: true,
  blood_group: null, skills: { teach: [], learn: [] }, name_locked_days: 0 };
const USER_CAROL = { telegram_id: 1993, first_name: "Carol", username: "carol",
  photo_file_id: null, cover_file_id: null, bio: "", followers: 0,
  following_count: 0, following: false, has_pending_request: false,
  blocked_by_me: false, muted_by_me: false, is_private: false,
  is_official: false, is_verified: false, portfolio_enabled: false,
  blood_group: null, skills: { teach: [], learn: [] }, name_locked_days: 0 };
global.fetch = async (url, opts) => {
  const path = String(url).split("?")[0];
  let data = {};
  if (path === "/auth") data = HARNESS_ME;
  else if (path === "/users/1992") data = USER_BOB;
  else if (path === "/users/1993") data = USER_CAROL;
  else if (path === "/users/1992/portfolio") data = PF_BOB;
  else if (path === "/users/1993/portfolio") data = {};
  else if (path === "/me/portfolio") data = PF_BOB;
  else if (path === "/highlights/user/1992") data = { highlights: [] };
  else if (path === "/highlights/user/1993") data = { highlights: [] };
  else if (path === "/users/1992/posts") data = { posts: [{ id: 11, type: "photo", caption: "Poster work", media_file_id: "pf_photo_1" }], next_cursor: null };
  else if (path === "/users/1993/posts") data = { posts: [], next_cursor: null };
  else if (path === "/feed") data = { posts: [], next_cursor: null };
  else if (path === "/designs") data = { designs: [] };
  return { ok: true, status: 200, json: async () => data, text: async () => "" };
};
'''

APP_MAIN = r'''
// me / profileTab / profileUser are `let` in app.js, so they do not
// leak out of a sloppy eval — export them from INSIDE the eval.
try {
  eval(APP_SRC_199 + "\n;globalThis.__nx199 = { getMe: () => me, setMe: (v) => { me = v; }, getTab: () => profileTab, getUser: () => profileUser, openProfile, openPortfolioEditor, renderPortfolioTab };");
  console.log("EVAL_OK: app.js parsed and top-level ran without throwing");
} catch (e) {
  console.log("EVAL_THROW: " + (e && e.message));
  process.exit(3);
}
(async () => {
  await sleep(50); // let loadMe()/bootOk settle
  assert(__nx199.getMe() && __nx199.getMe().telegram_id === 1991,
    "boot sets me from the /auth stub (Alice)");
  const box = document.getElementById("profile-box");
  // 1. Bob (portfolio ON): default tab is Profile, dropdown present.
  await __nx199.openProfile(1992);
  assert(__nx199.getTab() === "profile", "profile default tab is Profile");
  assert(__nx199.getUser() && __nx199.getUser().telegram_id === 1992,
    "profileUser is Bob");
  assert(findByClass(box, "pf-dd-wrap").length === 1,
    "dropdown present when the portfolio is on");
  const btn = findBtn(box, "Profile ▾");
  assert(btn, "dropdown button reads Profile ▾ on the Profile tab");
  const menu = findByClass(box, "pf-dd-menu")[0];
  assert(menu && menu.hidden === true, "dropdown menu starts closed");
  btn.onclick();
  assert(menu.hidden === false, "dropdown opens on tap");
  // 2. Switch to Portfolio: cover + shade + name/role + work grid.
  const pfOpt = findBtn(box, "Portfolio");
  assert(pfOpt, "Portfolio option present");
  await pfOpt.onclick();
  assert(__nx199.getTab() === "portfolio", "tab switches to portfolio");
  const cover = findByClass(box, "pf-cover")[0];
  assert(cover, "portfolio cover present");
  let coverImg = null;
  for (const ch of cover.children) if (ch.tag === "img") coverImg = ch;
  assert(coverImg && coverImg.src.indexOf("pf_cover_1") >= 0,
    "cover photo is the portfolio cover");
  assert(findByClass(box, "pf-shade").length === 1,
    "light shadow over the cover");
  const nameEl = findByClass(box, "pf-name")[0];
  assert(nameEl && visibleText(nameEl).indexOf("Bob") >= 0,
    "name sits over the shadow");
  const roleEl = findByClass(box, "pf-role")[0];
  assert(roleEl && roleEl.textContent === "Designer", "role over the shadow");
  assert(findByClass(box, "pf-about")[0].textContent === "About Bob",
    "about section renders");
  const grid = findByClass(box, "pf-work-grid")[0];
  assert(grid, "work grid present");
  const cards = findByClass(grid, "pf-work-card");
  assert(cards.length === 2, "2 work cards, got " + cards.length);
  assert(findByClass(cards[0], "pf-work-title")[0].textContent === "Poster",
    "first card title");
  assert(findBtn(box, "Follow"), "Follow button on the portfolio");
  assert(findBtn(box, "💬 Message"), "Message button on the portfolio");
  // 3. Back to Profile via the dropdown.
  const backBtn = findBtn(box, "Portfolio ▾");
  assert(backBtn, "dropdown reads Portfolio ▾ on the Portfolio tab");
  backBtn.onclick();
  const profOpt = findBtn(box, "Profile");
  assert(profOpt, "Profile option present (Portfolio is the current one)");
  await profOpt.onclick();
  assert(__nx199.getTab() === "profile", "back on the Profile tab");
  assert(findByClass(box, "pf-dd-wrap").length === 1, "dropdown still present");
  assert(findByClass(box, "pf-cover").length === 0,
    "portfolio cover gone on Profile");
  // 4. Carol (portfolio OFF): no dropdown at all.
  await __nx199.openProfile(1993);
  assert(__nx199.getTab() === "profile", "Carol default tab is Profile");
  assert(findByClass(box, "pf-dd-wrap").length === 0,
    "no dropdown when the portfolio is off");
  // 5. Editor (as Bob): toggle + role/about + save + work list + gallery upload.
  __nx199.setMe({ telegram_id: 1992, first_name: "Bob", username: "bob",
    is_admin: false, photo_file_id: "pf_bob_photo", media_token: "" });
  await __nx199.openPortfolioEditor();
  assert(__nx199.getTab() === "portfolio", "editor sets the portfolio tab");
  let enChk = null; let roleIn = null; let aboutIn = null;
  const walk = (el) => {
    for (const ch of el.children) {
      if (ch.tag === "input" && ch.type === "checkbox") enChk = ch;
      // First text input wins: the role field comes before the
      // add-sample title field later in the editor.
      if (ch.tag === "input" && ch.type === "text" && !roleIn) roleIn = ch;
      if (ch.tag === "textarea") aboutIn = ch;
      walk(ch);
    }
  };
  walk(box);
  assert(enChk && enChk.checked === true, "enable toggle reflects the ON state");
  assert(roleIn && roleIn.value === "Designer", "role input prefilled");
  assert(aboutIn && aboutIn.value === "About Bob", "about prefilled");
  assert(findBtn(box, "Save portfolio"), "Save portfolio button");
  // The editor builds the list with workList.id = "pf-edit-list"
  // on a created element, so find the rows under the box rather
  // than through getElementById (the stub only tracks ids it
  // created itself).
  const rows = findByClass(box, "pf-edit-row");
  assert(rows.length === 2, "2 work rows, got " + rows.length);
  const coverBtn = findBtn(box, "📷 Upload cover from gallery");
  assert(coverBtn, "cover upload button");
  // Phase 204: the cover button opens the phone gallery — the
  // hidden file input's click, not a picker. The stub input's
  // click is a no-op, so record it first.
  const fileInputs = [];
  const walkFiles = (el) => {
    for (const ch of el.children) {
      if (ch.tag === "input" && ch.type === "file") fileInputs.push(ch);
      walkFiles(ch);
    }
  };
  walkFiles(box);
  assert(fileInputs.length === 2,
    "cover + work file inputs, got " + fileInputs.length);
  fileInputs.forEach((fi) => {
    assert(fi.accept === "image/*", "file input accepts images only");
    assert(fi.hidden === true, "file input is hidden");
  });
  let coverClicked = false;
  fileInputs[0].click = () => { coverClicked = true; };
  coverBtn.onclick();
  assert(coverClicked, "cover button opens the gallery file input");
  assert(typeof fileInputs[0].onchange === "function",
    "cover input has an upload handler");
  // Work add: title + one gallery upload button, no kind select,
  // no pick buttons.
  const upBtn = findBtn(box, "📷 Upload from gallery");
  assert(upBtn, "work upload button");
  let titleIn = null;
  const walkTitle = (el) => {
    for (const ch of el.children) {
      if (ch.tag === "input" && ch.type === "text"
          && ch.placeholder === "Work sample title") titleIn = ch;
      walkTitle(ch);
    }
  };
  walkTitle(box);
  assert(titleIn, "work title input");
  let selects = 0;
  const walkSel = (el) => {
    for (const ch of el.children) {
      if (ch.tag === "select") selects++;
      walkSel(ch);
    }
  };
  walkSel(box);
  assert(selects === 0, "no kind select in the editor, got " + selects);
  assert(!findBtn(box, "📷 Choose one of my posts"), "no post picker");
  assert(!findBtn(box, "🎨 Choose a design"), "no design picker");
  assert(!findBtn(box, "🖼️ Choose a photo"), "no photo picker");
  assert(typeof fileInputs[1].onchange === "function",
    "work input has an upload handler");
  console.log("APP HARNESS OK (phase-199: dropdown default Profile, portfolio render, editor + gallery upload)");
  process.exit(0);
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_app_harness():
    src = open(os.path.join(ROOT, "code/webapp/app.js")).read()
    harness = (APP_PRELUDE
               + "\nconst APP_SRC_199 = " + json.dumps(src) + ";\n"
               + APP_MAIN)
    path = "/tmp/t199_app_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "EVAL_OK" in r.stdout, (r.stdout, r.stderr)
    assert "APP HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("app node harness OK (dropdown default Profile, portfolio "
          "render, editor + gallery upload)")


_run_app_harness()
print("PHASE 199 OK")
