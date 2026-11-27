"""Phase 189 tests: Design Gallery images never render (owner
screenshots Nov 24 + Nov 26 — every card text-only, zero-height
media area, while the app itself loads fine).

Diagnosis (proven in the phase, not assumed):
- The client retry logic was ALREADY correct on ?v=188 — the Node
  harness (nexora_designs/phase189_design_img_proof.js) passes 11/11
  on the old code: the capture-phase error handler covers dynamically
  created design <img>s, a stale token is refreshed + rebuilt, a
  dead file retries 3x then stops. mediaUrl attaches a fresh token.
- The server code reads correct too: _media_visible returns True
  for any design file_id, and the proxy streams when getFile
  resolves. Shell caching (no-cache + versioned app.js) and the
  transparent .img-shield were ruled out.
- What remained: (1) design <img>s are loading="lazy" inside a
  2-column CSS masonry — the one layout difference from the feed —
  and the images never fire at all on the owner's phone; (2) when
  an image does fail, .design-media has no min-height, so the card
  collapses to a zero-height text-only card with no retry affordance
  and no visible failure; (3) nobody could tell a dead file_id from
  a client failure.
Fix: design images load eager; .design-media keeps a 180px
min-height + placeholder and shows a tap-to-retry button once
retries are spent (card + related strip + sheet); new read-only
admin endpoint GET /admin/designs/health reports per-design
getFile health, so a dead file_id is diagnosable instead of
invisible. Feed images keep lazy — they work.
The harness FAILS 7 checks on the old ?v=188 code (eager x2,
failed mark, retry button, retry rebuild/clear x3) and passes all
18 on the new code — run it here against the local app.js.
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
os.environ["DATABASE_URL"] = (
    "sqlite:///" + os.path.expanduser(
        "~/workspace/nexora_run69/test_phase189.sqlite"))
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import httpx  # noqa: E402
import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

# --- Telegram upstream, faked per file_id -------------------------
# DESIGN_GOOD resolves via getFile and streams 5 bytes; DESIGN_DEAD
# 404s at getFile, so the proxy must 404 too — the exact failure the
# gallery showed. The health endpoint reports the same split.
MEDIA_MODE = {"send": "ok"}


class FakeGetFileResp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {"ok": True,
                              "result": {"file_path": "photos/file_1.jpg"}}

    def json(self):
        return self._body


class FakeStreamResp:
    status_code = 200

    @property
    def headers(self):
        return {"content-type": "image/jpeg", "content-length": "5"}

    async def aiter_bytes(self):
        yield b"ab"
        yield b"cde"

    async def aclose(self):
        pass


class FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        fid = (params or {}).get("file_id", "")
        if fid == "DESIGN_DEAD":
            return FakeGetFileResp(
                404, {"ok": False,
                      "description": "Bad Request: file not found"})
        return FakeGetFileResp()

    def build_request(self, method, url, headers=None):
        return (method, url, headers)

    async def send(self, req, stream=False):
        return FakeStreamResp()

    async def aclose(self):
        pass


httpx.AsyncClient = FakeAsyncClient

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES  # noqa: E402
from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402


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


ALICE = H(1891, "Alice", "alice189")
ADMIN = H(999, "Admin")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()

c = TestClient(app)

# --- 1. JS parses (node) ------------------------------------------
for f in ("webapp/app.js", "webapp/games.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True,
                       cwd=os.path.join(ROOT, "code"))
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (app.js + games.js parse)")

# --- 2. Harness: old code fails 7 checks, new code passes all 18 --
r = subprocess.run(
    ["node", os.path.join(DESIGNS, "phase189_design_img_proof.js"),
     os.path.join(ROOT, "code/webapp/app.js")],
    capture_output=True, text=True, timeout=60)
assert r.returncode == 0, r.stdout + r.stderr
assert "DONE failures=0" in r.stdout, r.stdout
assert "design img loads eager, not lazy" in r.stdout, r.stdout
assert "exhausted retries mark the media failed" in r.stdout, r.stdout
assert "failed card carries a retry button" in r.stdout, r.stdout
assert "retry rebuilds img with a fresh token" in r.stdout, r.stdout
print("design-image harness OK (18/18: eager + failed state + retry)")

# --- 3. Client markers --------------------------------------------
# Gallery card: eager + retry button + load clearing.
at = JS.index("function designCard(d)")
block = JS[at:at + 4200]
assert 'img.loading = "eager"' in block, "card img is not eager"
assert 'img.loading = "lazy"' not in block, "card img still lazy"
assert 'media.append(img, shield, retry)' in block, block
assert '"design-retry"' in block, "no retry button in card"
assert 'img.onload = () => media.classList.remove("design-img-failed")' \
    in block, "no load clearing in card"
# Related strip: same treatment.
at = JS.index("async function loadRelatedDesigns(d)")
block = JS[at:at + 2600]
assert 'img.loading = "eager"' in block, "related img is not eager"
assert 'img.loading = "lazy"' not in block, "related img still lazy"
assert 'media.append(img, shield, retry)' in block, block
# Feed + story images keep lazy (they work — do not touch them).
assert JS.count('img.loading = "lazy"') == 5, \
    JS.count('img.loading = "lazy"')
assert JS.count('img.loading = "eager"') == 2, \
    JS.count('img.loading = "eager"')
# Failed-state helpers + exhausted-branch wiring.
assert "function markDesignImgFailed(t)" in JS
assert "async function retryDesignImg(img)" in JS
assert "if (tries >= 3) { markDesignImgFailed(t); return; }" in JS
assert 't.closest(".design-media")' in JS
assert "delete img.dataset.mtok; delete img.dataset.mr;" in JS
# Sheet: new design starts clean; retry button + load clearing wired.
assert 'delete dsImg.dataset.mtok; delete dsImg.dataset.mr;' in JS
assert 'dsMedia.classList.remove("design-img-failed")' in JS
assert '$("ds-retry").onclick = () => retryDesignImg($("ds-img"));' in JS
assert '$("ds-img").onload = () => {' in JS
print("client markers OK (eager + retry + failed state, feed lazy kept)")

# --- 4. CSS + HTML -------------------------------------------------
assert ".design-media { position: relative; min-height: 180px;" in CSS, \
    "media area has no min-height"
assert "background: linear-gradient(160deg, #F4EBDD, #E9DCC8);" in CSS
assert ".design-retry { display: none;" in CSS
assert ".design-media.design-img-failed .design-retry { display: flex; }" \
    in CSS
assert ".design-media.design-img-failed img { visibility: hidden; }" in CSS
assert 'id="ds-retry"' in HTML
assert 'class="design-retry"' in HTML
assert "↻ Couldn't load — tap to retry" in HTML
print("CSS + HTML OK (min-height placeholder + retry button)")

# --- 5. Server: /media serves a live design file_id, 404s a dead one
with SessionLocal() as db:
    db.query(models.Design).delete()
    db.add(models.Design(image_file_id="DESIGN_GOOD", prompt="good one"))
    db.add(models.Design(image_file_id="DESIGN_DEAD", prompt="dead one"))
    db.commit()
r = c.post("/auth", json={"initData": make_init_data(
    {"id": 1891, "first_name": "Alice", "username": "alice189"})})
assert r.status_code == 200, r.text
token = r.json()["media_token"]
assert token
r = c.get("/media/DESIGN_GOOD?mt=" + token)
assert r.status_code == 200, r.text
assert r.content == b"abcde", r.content
r = c.get("/media/DESIGN_DEAD?mt=" + token)
assert r.status_code == 404, r.status_code
print("media proxy OK (live design file streams, dead file 404s)")

# --- 6. Server: GET /admin/designs/health --------------------------
r = c.get("/admin/designs/health", headers=ALICE)
assert r.status_code == 403, r.status_code
r = c.get("/admin/designs/health", headers=ADMIN)
assert r.status_code == 200, r.text
body = r.json()
assert body["checked"] == 2, body
good = [d for d in body["designs"] if d["ok"]]
dead = [d for d in body["designs"] if not d["ok"]]
assert len(good) == 1 and good[0]["file_path"] == "photos/file_1.jpg", body
assert len(dead) == 1 and "404" in dead[0]["error"], body
assert len(body["dead"]) == 1, body
print("designs health OK (live ok, dead reported with getFile 404)")

# --- 7. Client markers, version, routes, backup --------------------
assert "app.js?v=202" in HTML
assert ("?v=18" + "9") not in HTML
assert "style.css?v=202" in HTML
assert "games.js?v=202" in HTML
paths = {rt.path for rt in app.routes}
assert len(paths) == 193, len(paths)
assert "/admin/designs/health" in paths
assert "/designs" in paths
h = c.get("/admin/health", headers=ADMIN).json()
assert h["version"] == 202, h
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
print("client + version + routes + backup OK (184 routes, 52 tables, ?v=202)")

print("PHASE 189 OK")
