"""Phase 204 tests: gallery upload at EVERY upload point.

Server: the two new portfolio upload endpoints (cover + work
sample, fresh from the phone gallery), the _own_media_file_ids
extension (a fresh portfolio photo counts as your own photo,
so saving after a fresh cover upload works), and X-Upload-Id
dedupe on /posts/upload-media, /me/photo/upload,
/me/cover/upload and /designs/{id}/edit. Client: the portfolio
pickers are gone, the editor is gallery upload, and every
upload point rides the shared hardened path (shrink +
apiFormProgress + newUploadId). A Node harness drives the real
app.js editor through a cover upload and a work upload.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase204.db"
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
from app.db import SessionLocal  # noqa: E402
import app.main as main_mod  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(2041, "Alice", "alice")
BOB = H(2042, "Bob", "bob")
CAROL = H(2043, "Carol", "carol")
ADMIN = H(999, "Admin", "admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()

# Uploads never reach Telegram in tests: the sender is stubbed
# and hands back a fresh file_id per call, so a dedupe replay
# can be told apart from a genuinely new upload.
_upload_calls = []


async def fake_upload(user, file, caption=""):
    fid = "up204_%d" % (len(_upload_calls) + 1)
    _upload_calls.append(fid)
    return ("photo", fid)


main_mod._telegram_upload_or_400 = fake_upload

PNG = ("c.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")
TXT = ("c.txt", b"hello", "text/plain")

c = TestClient(app)


def mk(uid, name, username):
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text


mk(2041, "Alice", "alice")
mk(2042, "Bob", "bob")
mk(2043, "Carol", "carol")
mk(999, "Admin", "admin")

db = SessionLocal()
try:
    if not db.query(models.BannedWord).filter_by(word="zqxjword").first():
        db.add(models.BannedWord(word="zqxjword", added_by=999))
        db.commit()
finally:
    db.close()

# --- 1. Routes + version. --------------------------------------
paths = {rt.path for rt in app.routes}
assert len(paths) == 191, len(paths)
for want in ("/me/portfolio/cover/upload", "/me/portfolio/items/upload"):
    assert want in paths, want
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert HTML.count("?v=206") == 10, HTML.count("?v=206")
assert "?v=20" + "5" not in HTML
assert "app.js?v=206" in HTML and "games.js?v=206" in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert "/?v=206" in BOT and "/?v=20" + "3" not in BOT
print("1. routes + version OK")

# --- 2. Portfolio cover upload: fresh from the gallery. ---------
# A non-photo is refused before any upload happens.
r = c.post("/me/portfolio/cover/upload", headers=ALICE, files={"file": TXT})
assert r.status_code == 400, r.text
assert len(_upload_calls) == 0
n0 = len(_upload_calls)
r = c.post("/me/portfolio/cover/upload",
           headers={**ALICE, "X-Upload-Id": "cov-1"},
           files={"file": PNG})
assert r.status_code == 200, r.text
cover_fid = "up204_%d" % (n0 + 1)
assert r.json()["cover_file_id"] == cover_fid, r.text
assert len(_upload_calls) == n0 + 1
# Replaying the same upload id: same cover, no second send.
r2 = c.post("/me/portfolio/cover/upload",
            headers={**ALICE, "X-Upload-Id": "cov-1"},
            files={"file": PNG})
assert r2.status_code == 200, r2.text
assert r2.json()["cover_file_id"] == cover_fid
assert len(_upload_calls) == n0 + 1, "dedupe replay re-uploaded"
# THE regression the _own_media_file_ids fix addresses: saving
# the portfolio (about/role/toggle) after a fresh cover upload
# used to 400 on its own cover_file_id.
r = c.post("/me/portfolio", headers=ALICE,
           json={"about": "About Alice", "role": "Designer",
                 "cover_file_id": cover_fid, "enabled": False})
assert r.status_code == 200, r.text
assert r.json()["cover_file_id"] == cover_fid
r = c.post("/me/portfolio", headers=ALICE,
           json={"about": "About Alice", "role": "Designer",
                 "cover_file_id": cover_fid, "enabled": True})
assert r.status_code == 200, r.text
# A stranger can load the fresh cover while the portfolio is on.
db = SessionLocal()
try:
    assert _media_visible(db, 2043, cover_fid) is True
finally:
    db.close()
r = c.post("/me/portfolio", headers=ALICE,
           json={"about": "About Alice", "role": "Designer",
                 "cover_file_id": cover_fid, "enabled": False})
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 2043, cover_fid) is False
finally:
    db.close()
print("2. portfolio cover upload + save-after-cover + visibility OK")

# --- 3. Work-sample upload: fresh from the gallery. -------------
r = c.post("/me/portfolio/items/upload", headers=ALICE,
           files={"file": PNG}, data={"title": ""})
assert r.status_code == 400, r.text
r = c.post("/me/portfolio/items/upload", headers=ALICE,
           files={"file": PNG}, data={"title": "zqxjword"})
assert r.status_code == 400, r.text
r = c.post("/me/portfolio/items/upload", headers=ALICE,
           files={"file": TXT}, data={"title": "Sketch"})
assert r.status_code == 400, r.text
n0 = len(_upload_calls)
r = c.post("/me/portfolio/items/upload",
           headers={**ALICE, "X-Upload-Id": "work-1"},
           files={"file": PNG}, data={"title": "  My Poster  "})
assert r.status_code == 200, r.text
work_fid = "up204_%d" % (n0 + 1)
d = r.json()
assert d["kind"] == "project" and d["ref_id"] is None, d
assert d["title"] == "My Poster" and d["image_file_id"] == work_fid, d
work_id = d["id"]
# Replay: same item, no second upload, no duplicate item.
r2 = c.post("/me/portfolio/items/upload",
            headers={**ALICE, "X-Upload-Id": "work-1"},
            files={"file": PNG}, data={"title": "My Poster"})
assert r2.status_code == 200, r2.text
assert r2.json()["id"] == work_id
assert len(_upload_calls) == n0 + 1
r = c.get("/me/portfolio", headers=ALICE)
assert r.status_code == 200, r.text
assert len(r.json()["items"]) == 1, r.json()
# The fresh work image loads for strangers while on.
r = c.post("/me/portfolio", headers=ALICE,
           json={"about": "About Alice", "role": "Designer",
                 "cover_file_id": cover_fid, "enabled": True})
assert r.status_code == 200, r.text
db = SessionLocal()
try:
    assert _media_visible(db, 2043, work_fid) is True
finally:
    db.close()
print("3. work-sample upload + dedupe + visibility OK")

# --- 3b. 20-item cap on the upload path. -------------------------
db = SessionLocal()
try:
    pf = models.Portfolio(user_id=2042)
    db.add(pf)
    db.commit()
    db.refresh(pf)
    for i in range(20):
        db.add(models.PortfolioItem(portfolio_id=pf.id, kind="project",
                                    ref_id=None, title="T%d" % i,
                                    image_file_id="seed_%d" % i, position=i))
    db.commit()
finally:
    db.close()
r = c.post("/me/portfolio/items/upload", headers=BOB,
           files={"file": PNG}, data={"title": "One too many"})
assert r.status_code == 400, r.text
print("3b. 20-item cap OK")

# --- 4. Dedupe on the hardened upload endpoints. -----------------
# Profile photo.
n0 = len(_upload_calls)
r = c.post("/me/photo/upload", headers={**ALICE, "X-Upload-Id": "ph-1"},
           files={"file": PNG})
assert r.status_code == 200, r.text
assert r.json()["photo_file_id"] == "up204_%d" % (n0 + 1), r.text
r2 = c.post("/me/photo/upload", headers={**ALICE, "X-Upload-Id": "ph-1"},
            files={"file": PNG})
assert r2.json()["photo_file_id"] == r.json()["photo_file_id"]
assert len(_upload_calls) == n0 + 1
# Cover photo.
n0 = len(_upload_calls)
r = c.post("/me/cover/upload", headers={**ALICE, "X-Upload-Id": "cv-1"},
           files={"file": PNG})
assert r.status_code == 200, r.text
assert r.json()["cover_file_id"] == "up204_%d" % (n0 + 1), r.text
r2 = c.post("/me/cover/upload", headers={**ALICE, "X-Upload-Id": "cv-1"},
            files={"file": PNG})
assert r2.json()["cover_file_id"] == r.json()["cover_file_id"]
assert len(_upload_calls) == n0 + 1
# Album staging.
n0 = len(_upload_calls)
r = c.post("/posts/upload-media", headers={**ALICE, "X-Upload-Id": "st-1"},
           files={"file": PNG})
assert r.status_code == 200, r.text
assert r.json()["file_id"] == "up204_%d" % (n0 + 1), r.text
r2 = c.post("/posts/upload-media", headers={**ALICE, "X-Upload-Id": "st-1"},
            files={"file": PNG})
assert r2.json()["file_id"] == r.json()["file_id"]
assert len(_upload_calls) == n0 + 1
# Design edit (admin): create a design, then edit it twice.
r = c.post("/designs/upload", headers=ADMIN,
           files={"file": PNG}, data={"prompt": "Sunset logo"})
assert r.status_code == 200, r.text
did = r.json()["id"]
n0 = len(_upload_calls)
r = c.post("/designs/%d/edit" % did,
           headers={**ADMIN, "X-Upload-Id": "de-1"},
           files={"file": PNG}, data={"prompt": "Sunset logo v2"})
assert r.status_code == 200, r.text
assert r.json()["image_file_id"] == "up204_%d" % (n0 + 1), r.text
r2 = c.post("/designs/%d/edit" % did,
            headers={**ADMIN, "X-Upload-Id": "de-1"},
            files={"file": PNG}, data={"prompt": "Sunset logo v2"})
assert r2.json()["image_file_id"] == r.json()["image_file_id"]
assert len(_upload_calls) == n0 + 1
print("4. dedupe on photo/cover/staging/design-edit OK")

# --- 5. Client: pickers gone, gallery upload everywhere. ---------
for m in ("/me/portfolio/cover/upload", "/me/portfolio/items/upload",
          "📷 Upload cover from gallery", "📷 Upload from gallery",
          "Work sample title",
          "Add samples fresh from your phone gallery."):
    assert m in JS, f"missing JS marker: {m}"
for m in ("async function portfolioPickPhotos",
          "async function portfolioPickPosts",
          "async function portfolioPickDesigns",
          "portfolioPickPhotos(", "portfolioPickPosts(",
          "portfolioPickDesigns(", "Choose cover photo",
          "Choose one of my posts", "Choose a design",
          "Choose a photo", "From one of my posts",
          "From the Design gallery", "Project (my own photo)",
          "Add samples from your posts, the Design gallery or your own photos."):
    assert m not in JS, f"removed picker marker still present: {m}"
# Every upload point rides the hardened path now — plain apiForm
# has no call sites left, only its own definition.
assert JS.count("apiForm(") == 1, JS.count("apiForm(")
for m in ('apiFormProgress("/me/photo/upload", form,',
          'apiFormProgress("/me/cover/upload", form,',
          '"/designs/" + currentDesign.id + "/edit", form,',
          '"/posts/upload-media", form, () => {}, newUploadId()',
          'apiFormProgress("/me/portfolio/cover/upload"',
          'apiFormProgress("/me/portfolio/items/upload", form,'):
    assert m in JS, f"missing hardened call: {m}"
# Story upload carries its own upload id now (was null).
_s0 = JS.index('$("story-file").addEventListener')
_s1 = JS.index("function stopStoryTimer()", _s0)
_story = JS[_s0:_s1]
assert "newUploadId()" in _story, "story upload has no upload id"
assert ", null);" not in _story, "story upload still passes null"
print("5. client markers + hardened path OK")

# --- 6. Node harness: real app.js editor, cover + work upload. ----
APP_PRELUDE = r'''
// Phase-204 app harness: run the real app.js with window.Telegram
// MISSING (the Phase-188 boot-proof setup), a TRACKED byId
// registry, and fetch + XHR stubs. The DOM stub's querySelectorAll
// searches descendants by class/tag and an innerHTML assignment
// clears children.
function makeEl204(tag) {
  const el = {
    tag: tag || "div", children: [], parent: null, hidden: false,
    id: "", className: "", textContent: "", value: "", type: "",
    checked: false, disabled: false, maxLength: 0, placeholder: "",
    rows: 0, src: "", href: "", alt: "", loading: "", title: "",
    accept: "", files: null, onclick: null, onchange: null,
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
const __body204 = makeEl204("body");
const __docEl204 = makeEl204("html");
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
  getElementById(id) { if (!this._byId[id]) { const e = makeEl204("div"); e.id = id; this._byId[id] = e; } return this._byId[id]; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(t) { return makeEl204(t); },
  createTextNode(text) { const n = makeEl204("#text"); n.textContent = text; return n; },
  addEventListener() {}, removeEventListener() {},
  body: __body204, documentElement: __docEl204, title: "", hidden: false,
};
const _store204 = new Map();
global.localStorage = { getItem: (k) => _store204.has(k) ? _store204.get(k) : null, setItem: (k, v) => _store204.set(k, String(v)), removeItem: (k) => _store204.delete(k) };
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
// --- stubbed server state: Alice (me) edits her own portfolio.
let HARNESS_ME = { telegram_id: 2041, first_name: "Alice", username: "alice",
  is_admin: false, photo_file_id: null, media_token: "" };
const PF204 = { user_id: 2041, first_name: "Alice", username: "alice",
  photo_file_id: null, is_verified: false, about: "About Alice",
  role: "Designer", cover_file_id: null, enabled: true, items: [] };
global.fetch = async (url, opts) => {
  const path = String(url).split("?")[0];
  let data = {};
  if (path === "/auth") data = HARNESS_ME;
  else if (path === "/me/portfolio") data = PF204;
  return { ok: true, status: 200, json: async () => data, text: async () => "" };
};
// --- XHR stub: records every upload, answers like the server.
const XHR_LOG = [];
function XHR_RESPOND(url, body) {
  if (url === "/me/portfolio/cover/upload") {
    PF204.cover_file_id = "pf_up_cover";
    return PF204;
  }
  if (url === "/me/portfolio/items/upload") {
    const it = { id: 1, kind: "project", ref_id: null,
      title: "My Project", image_file_id: "pf_up_work" };
    PF204.items.push(it);
    return it;
  }
  return {};
}
global.XMLHttpRequest = class {
  constructor() {
    this.upload = {}; this.headers = {}; this.status = 0;
    this.responseText = ""; this.timeout = 0;
  }
  open(method, url) { this._method = method; this._url = url; }
  setRequestHeader(k, v) { this.headers[k] = v; }
  send(body) {
    const title = (body && body.get) ? body.get("title") : null;
    const file = (body && body.get) ? body.get("file") : null;
    XHR_LOG.push({ method: this._method, url: this._url,
      headers: this.headers, title: title,
      fileName: file ? file.name : null });
    const self = this;
    setTimeout(() => {
      self.status = 200;
      self.responseText = JSON.stringify(XHR_RESPOND(self._url, body));
      if (self.upload.onload) self.upload.onload();
      if (self.onload) self.onload();
    }, 0);
  }
};
'''

APP_MAIN = r'''
try {
  eval(APP_SRC_204 + "\n;globalThis.__nx204 = { getMe: () => me, openPortfolioEditor };");
  console.log("EVAL_OK: app.js parsed and top-level ran without throwing");
} catch (e) {
  console.log("EVAL_THROW: " + (e && e.message));
  process.exit(3);
}
(async () => {
  await sleep(50); // let loadMe()/bootOk settle
  assert(__nx204.getMe() && __nx204.getMe().telegram_id === 2041,
    "boot sets me from the /auth stub (Alice)");
  const box = document.getElementById("profile-box");
  await __nx204.openPortfolioEditor();
  // 1. Cover upload: button opens the gallery input; picking a
  // file posts it to /me/portfolio/cover/upload with an upload
  // id, and the preview shows the uploaded cover.
  const coverBtn = findBtn(box, "📷 Upload cover from gallery");
  assert(coverBtn, "cover upload button");
  const fileInputs = [];
  const walkFiles = (el) => {
    for (const ch of el.children) {
      if (ch.tag === "input" && ch.type === "file") fileInputs.push(ch);
      walkFiles(ch);
    }
  };
  walkFiles(box);
  assert(fileInputs.length === 2, "cover + work file inputs, got " + fileInputs.length);
  fileInputs[0].files = [new File([Buffer.from("cover-bytes")], "cover.png", { type: "image/png" })];
  await fileInputs[0].onchange();
  await sleep(10);
  const coverReq = XHR_LOG.find(r => r.url === "/me/portfolio/cover/upload");
  assert(coverReq, "cover upload posted");
  assert(coverReq.headers["X-Upload-Id"], "cover upload carries an upload id");
  assert(coverReq.fileName === "cover.png", "cover file sent, got " + coverReq.fileName);
  const coverPrev = findByClass(box, "pf-edit-cover")[0];
  assert(coverPrev, "cover preview present");
  const prevImgs = [];
  const walkImgs = (el) => {
    for (const ch of el.children) {
      if (ch.tag === "img") prevImgs.push(ch);
      walkImgs(ch);
    }
  };
  walkImgs(coverPrev);
  assert(prevImgs.length === 1 && prevImgs[0].src.indexOf("pf_up_cover") >= 0,
    "preview shows the uploaded cover");
  // 2. Work upload: title + gallery file posts to
  // /me/portfolio/items/upload with the title attached; the
  // list refreshes with the new row.
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
  titleIn.value = "My Project";
  const upBtn = findBtn(box, "📷 Upload from gallery");
  assert(upBtn, "work upload button");
  fileInputs[1].files = [new File([Buffer.from("work-bytes")], "work.png", { type: "image/png" })];
  upBtn.onclick();
  await fileInputs[1].onchange();
  await sleep(10);
  const workReq = XHR_LOG.find(r => r.url === "/me/portfolio/items/upload");
  assert(workReq, "work upload posted");
  assert(workReq.headers["X-Upload-Id"], "work upload carries an upload id");
  assert(workReq.title === "My Project", "work title sent, got " + workReq.title);
  assert(workReq.fileName === "work.png", "work file sent, got " + workReq.fileName);
  const rows = findByClass(box, "pf-edit-row");
  assert(rows.length === 1, "1 work row after upload, got " + rows.length);
  console.log("APP HARNESS OK (phase-204: editor cover + work gallery upload)");
  process.exit(0);
})().catch(e => { console.error(e.stack || e); process.exit(1); });
'''


def _run_app_harness():
    src = open(os.path.join(ROOT, "code/webapp/app.js")).read()
    harness = (APP_PRELUDE
               + "\nconst APP_SRC_204 = " + json.dumps(src) + ";\n"
               + APP_MAIN)
    path = "/tmp/t204_app_harness.js"
    open(path, "w").write(harness)
    r = subprocess.run(["node", "--check", path], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "EVAL_OK" in r.stdout, (r.stdout, r.stderr)
    assert "APP HARNESS OK" in r.stdout, (r.stdout, r.stderr)
    print("app node harness OK (editor cover + work gallery upload)")


_run_app_harness()
print("PHASE 204 OK")
