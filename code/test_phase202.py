"""Phase 202 tests: Design Gallery speed + compact cards + purple band.

Owner bug report (Nov 27, 22:26 Dhaka, phone screenshot): (1) the
Design page loads / image previews take too long; (2) the text and
icons on design cards take too much space, making the designs look
bad; (3) a purple translucent band overflows the first card's meta
area.

Diagnosis (verified, not assumed):
- Speed: design images stream via media_proxy as the ORIGINAL
  full-size Telegram file and Phase 189 made gallery images load
  eager, so ~20 full-resolution photos fetch at once through the
  proxy. Fix: ?w=<240..1024> on /media returns a downscaled JPEG
  thumbnail (Pillow, max width w, quality 78); the grid + related
  strip use w=480, the sheet and downloads keep the full size.
- Compact card: the grid card is image-only — no prompt text, no
  meta row below the image (the full prompt lives in the detail
  sheet). Like + views ride as glass chips over the image's bottom
  corners; the like keeps its 44px touch target (Phase 99), its
  data-did and its pointer guards; the views chip keeps data-dviews.
- Purple band: pixel-measured on the owner's screenshot — a ~25px
  translucent purple ring confined to the FIRST card's meta area,
  extending past the card edges, no other card affected. The only
  purple translucent paint anywhere on design cards is the theme
  system: applyUserTheme derives --clay-shadow-sm from the member's
  card palette (deriveTheme: shadow = tint at 0.38) and
  .design-card wears it as its box-shadow; with the CSS-columns
  masonry + the cardIn entrance animation the shadow paints offset
  around the meta in the Telegram WebView. Fix (structural): design
  cards get a fixed NEUTRAL shadow (no theme var), no entrance
  animation, isolated paint, a solid body background, and the
  overlay like button loses the generic button's theme shadow.
  The owner's phone check is the final confirmation for the band.
- Phase 189 behaviour is KEPT: eager loading, min-height
  placeholder, failed state + tap-to-retry (the updated 189
  harness runs here too and must pass 18/18 with thumb URLs).
Plain script (run.sh runs it with python directly).
"""
import os
import subprocess

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = (
    "sqlite:///" + os.path.expanduser(
        "~/workspace/nexora_run69/test_phase202.sqlite"))
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

from io import BytesIO  # noqa: E402

from PIL import Image  # noqa: E402


def _jpeg(w, h, color=(200, 40, 40)):
    im = Image.new("RGB", (w, h), color)
    buf = BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


# A real 1200x800 JPEG the fake Telegram upstream "hosts".
ORIG_JPEG = _jpeg(1200, 800)
STREAM_BODY = {"data": ORIG_JPEG, "content_type": "image/jpeg"}

import httpx  # noqa: E402
import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll


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
        return {"content-type": STREAM_BODY["content_type"],
                "content-length": str(len(STREAM_BODY["data"]))}

    async def aiter_bytes(self):
        yield STREAM_BODY["data"]

    async def aread(self):
        return STREAM_BODY["data"]

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
from app.main import (app, _BACKUP_TABLES, _health_version,  # noqa: E402
                      _media_token)
from app import models  # noqa: E402
from app.db import SessionLocal  # noqa: E402

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

# --- 2. Phase 189 harness (updated for thumb URLs) still 18/18 ---
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
print("design-image harness OK (18/18 with thumb URLs)")

# --- 3. Client markers: thumbnails + image-only cards ------------
assert "function mediaUrl(id, opts) {" in JS
assert 'u += (u.includes("?") ? "&" : "?") + "w=480";' in JS
at = JS.index("function designCard(d)")
block = JS[at:JS.index("async function loadDesigns", at)]
assert 'img.src = mediaUrl(d.image_file_id, {thumb: true});' in block
assert 'img.loading = "eager"' in block
assert 'media.append(img, shield, retry)' in block
assert '"design-retry"' in block
assert 'img.onload = () => media.classList.remove("design-img-failed")' \
    in block
# No prompt text, no meta row on the grid card any more.
assert "design-card-body" not in block, "grid card still has a body"
assert "design-prompt" not in block, "grid card still shows the prompt"
assert "design-stats" not in block, "grid card still has a stats row"
# Like + views ride as overlay chips inside the media area.
assert '"design-like design-ov-like"' in block
assert '"design-views design-ov-views"' in block
assert "media.append(like, views)" in block
assert "el.append(media);" in block
assert "like.dataset.did = d.id;" in block
assert "views.dataset.dviews = d.id;" in block
# Related strip: thumbnails, still image-only, retry kept.
at = JS.index("async function loadRelatedDesigns(d)")
block = JS[at:at + 2600]
assert 'img.src = mediaUrl(rel.image_file_id, {thumb: true});' in block
assert 'img.loading = "eager"' in block
assert 'media.append(img, shield, retry)' in block
# Sheet + download keep the FULL-size image.
assert "dsImg.src = mediaUrl(d.image_file_id);" in JS
assert ("const url = location.origin + "
        "mediaUrl(currentDesign.image_file_id);") in JS
# Stale-token rebuild + tap-to-retry preserve the thumb flag.
assert '{thumb: src.includes("&w=480")}' in JS
assert ('{thumb: (img.getAttribute("src") || "")'
        '.includes("&w=480")}') in JS
# Eager/lazy counts unchanged from Phase 189.
assert JS.count('img.loading = "eager"') == 2, \
    JS.count('img.loading = "eager"')
assert JS.count('img.loading = "lazy"') == 5, \
    JS.count('img.loading = "lazy"')
print("client markers OK (thumbs + image-only cards, sheet full-size)")

# --- 4. CSS markers: neutral shadow + overlays (purple band) -----
assert (".design-card { box-shadow: 0 6px 18px "
        "rgba(60, 50, 40, .16);") in CSS
assert CSS.count(".design-card { box-shadow: 0 6px 18px "
                 "rgba(60, 50, 40, .16);") == 1
# The neutral rule must come AFTER the cardIn group rule it
# overrides, and after the theme-shadow rule it replaces.
assert (CSS.index("box-shadow: 0 6px 18px rgba(60, 50, 40, .16)") >
        CSS.index(".post, .design-card, .rank-row, .notif-row "
                  "{ animation: cardIn"))
assert (CSS.index("box-shadow: 0 6px 18px rgba(60, 50, 40, .16)") >
        CSS.index("box-shadow: var(--clay-shadow-sm); cursor: pointer;"))
assert ("animation: none; isolation: isolate; position: relative; }"
        in CSS)
assert ".design-card-body { background: #FFFBFC; }" in CSS
assert ".design-card .design-like { box-shadow: none; }" in CSS
assert (".design-ov-like { position: absolute; left: 8px; bottom: 8px; "
        "z-index: 3;") in CSS
assert (".design-ov-views { position: absolute; right: 8px; bottom: 8px; "
        "z-index: 3;") in CSS
assert ("border-radius: 999px; padding: 6px 10px; font-size: 12px;\n"
        "  pointer-events: none; }") in CSS
assert ".design-media.design-img-failed .design-ov-like," in CSS
assert (".design-media.design-img-failed .design-ov-views "
        "{ display: none; }") in CSS
# The Phase 189 guard rails are untouched.
assert ".design-media { position: relative; min-height: 180px;" in CSS
assert ".design-retry { display: none;" in CSS
assert ".design-media.design-img-failed .design-retry { display: flex; }" \
    in CSS
assert ".design-media.design-img-failed img { visibility: hidden; }" in CSS
print("CSS markers OK (neutral shadow + overlays, 189 rails kept)")

# --- 5. Server: /media ?w= thumbnails ------------------------------
with SessionLocal() as db:
    db.query(models.Design).delete()
    if db.get(models.User, 2021) is None:
        db.add(models.User(telegram_id=2021, first_name="Tess",
                           username="tess202"))
    db.add(models.Design(image_file_id="DESIGN_GOOD", prompt="good one"))
    db.add(models.Design(image_file_id="DESIGN_DEAD", prompt="dead one"))
    db.commit()
token = _media_token(2021)
assert token

# Full size, no w: the original bytes, untouched.
r = c.get("/media/DESIGN_GOOD?mt=" + token)
assert r.status_code == 200, r.text
assert r.content == ORIG_JPEG, len(r.content)
assert r.headers["content-type"] == "image/jpeg"

# Thumb: a real 480px JPEG, smaller than the original, cached.
r = c.get("/media/DESIGN_GOOD?mt=" + token + "&w=480")
assert r.status_code == 200, r.text
assert r.headers["content-type"] == "image/jpeg"
assert r.headers["cache-control"] == "private, max-age=3600, immutable"
thumb = Image.open(BytesIO(r.content))
thumb.load()
assert thumb.size == (480, 320), thumb.size
assert len(r.content) < len(ORIG_JPEG), \
    (len(r.content), len(ORIG_JPEG))
print(f"thumbnail OK (1200x800 -> {thumb.size}, "
      f"{len(ORIG_JPEG)} -> {len(r.content)} bytes)")

# Invalid w values fall back to the original stream.
for bad in ("abc", "50", "99999", "0", "-480"):
    r = c.get("/media/DESIGN_GOOD?mt=" + token + "&w=" + bad)
    assert r.status_code == 200 and r.content == ORIG_JPEG, bad
print("invalid w OK (falls back to original)")

# Range requests ignore w (video seeking path).
r = c.get("/media/DESIGN_GOOD?mt=" + token + "&w=480",
          headers={"Range": "bytes=0-99"})
assert r.status_code == 200 and r.content == ORIG_JPEG, r.status_code
print("Range + w OK (thumb skipped, original streamed)")

# Undecodable upstream falls back to the original bytes.
STREAM_BODY["data"] = b"not-an-image"
try:
    r = c.get("/media/DESIGN_GOOD?mt=" + token + "&w=480")
    assert r.status_code == 200 and r.content == b"not-an-image", r.text
finally:
    STREAM_BODY["data"] = ORIG_JPEG
print("non-image fallback OK (original bytes, no crash)")

# Auth + visibility still enforced on the thumb path.
r = c.get("/media/DESIGN_GOOD?w=480")
assert r.status_code == 401, r.status_code
r = c.get("/media/DESIGN_DEAD?mt=" + token + "&w=480")
assert r.status_code == 404, r.status_code
print("thumb auth OK (401 without token, 404 for dead file)")

# --- 6. Version, routes, backup ------------------------------------
assert "app.js?v=207" in HTML
assert ("?v=20" + "4") not in HTML
assert "style.css?v=207" in HTML
assert "games.js?v=207" in HTML
paths = {rt.path for rt in app.routes}
assert len(paths) == 191, len(paths)
assert "/media/{file_id}" in paths
assert "/designs" in paths
assert _health_version() == 207, _health_version()
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
print("version + routes + backup OK (191 routes, 55 tables, ?v=207)")

print("PHASE 202 OK")
