"""Phase-114 tests: My QR page (owner, Nov 13).

- Sidebar "My QR" page: each member's own profile link as a QR.
- Server-generated branded PNG (quiet zone + NEXORA SOCIAL at the
  bottom), fetched with a user-bound token; the QR encodes exactly
  the member's bot deep link ?start=profile_<id>.
- Bot /start profile_<id>: normal welcome + a View-profile button
  into the app (startapp link); unknown ids get no button.
- App reads start_param on launch and opens that profile
  (routeStartParam; openProfile itself handles a bad id).
"""
import asyncio
import hashlib
import hmac
import io
import json
import os
import time
import urllib.parse
from types import SimpleNamespace

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase114.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


CAROL, DAVE = H(333, "Carol"), H(444, "Dave")
PROFILE_LINK = "https://t.me/NexoraSocial_bot?start=profile_333"


def qr_matrix(link):
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q,
                       box_size=10, border=1)
    qr.add_data(link)
    qr.make(fit=True)
    return qr.get_matrix()


def sample_qr_grid(png_bytes):
    """Read the QR module grid back out of the branded PNG: the
    composition pastes the QR at (40, 40), 10 px per module."""
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes)).convert("L")
    w, h = img.size
    # modules = (width - 80) / 10 — the QR is square.
    n = (w - 80) // 10
    grid = []
    for r in range(n):
        row = []
        for c in range(n):
            px = img.getpixel((40 + c * 10 + 5, 40 + r * 10 + 5))
            row.append(px < 128)
        grid.append(row)
    return img, grid


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append((text, reply_markup))
        return None


def fake_update(uid, name):
    user = SimpleNamespace(id=uid, username=name.lower(),
                           first_name=name)
    return SimpleNamespace(effective_user=user, message=FakeMessage())


def profile_buttons(markup):
    out = []
    if markup is None:
        return out
    for row in markup.inline_keyboard:
        for b in row:
            out.append((b.text, b.url))
    return out


with TestClient(app) as c:
    for h in (CAROL, DAVE):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200

    # QR token + PNG for Carol.
    r = c.get("/me/qr-token", headers=CAROL)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert token
    r = c.get("/me/qr?qt=" + token)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png", r.headers
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    assert "max-age=86400" in r.headers.get("cache-control", "")
    png = r.content

    # The QR in the image encodes exactly Carol's profile link.
    img, grid = sample_qr_grid(png)
    expected = qr_matrix(PROFILE_LINK)
    assert len(grid) == len(expected), (len(grid), len(expected))
    assert grid == expected, "QR modules do not match the profile link"
    w, h = img.size
    assert h == w + 100, (w, h)  # bottom free space holds the label
    # Quiet zone: corners are white.
    for (x, y) in ((5, 5), (w - 5, 5), (5, h - 5), (w - 5, h - 5)):
        assert img.getpixel((x, y)) > 200, (x, y)
    # Bottom label: dark pixels in the free space below the QR.
    qr_bottom = 40 + len(expected) * 10
    dark = sum(
        1 for y in range(qr_bottom + 5, h - 5)
        for x in range(5, w - 5)
        if img.getpixel((x, y)) < 128)
    assert dark > 100, f"no NEXORA SOCIAL label drawn ({dark} dark px)"
    print("QR PNG encodes the profile link, quiet zone + label OK")

    # A different member gets different bytes; bad tokens are refused.
    r2 = c.get("/me/qr-token", headers=DAVE)
    png2 = c.get("/me/qr?qt=" + r2.json()["token"]).content
    assert png2 != png, "Dave's QR must differ from Carol's"
    assert c.get("/me/qr").status_code == 401
    assert c.get("/me/qr?qt=" + token[:-2] + "xx").status_code == 401
    print("per-member QR + token gate OK")

    # Bot /start with a profile payload: welcome names Dave and
    # offers the View-profile button into the app.
    db = SessionLocal()
    carol = db.get(models.User, 333)
    carol.photo_file_id = "FAKEPHOTO"
    db.commit()
    db.close()
    upd = fake_update(333, "Carol")
    asyncio.run(bot_mod.start_handler(
        upd, SimpleNamespace(args=["profile_444"])))
    assert len(upd.message.replies) == 1
    text, markup = upd.message.replies[0]
    assert "Dave" in text, text
    btns = profile_buttons(markup)
    assert any("profile_444" in (u or "") and "nexorasocial" in (u or "")
               for (_, u) in btns), btns
    assert any("View Dave" in t for (t, _) in btns), btns
    print("bot /start profile_444: welcome + View-profile button OK")

    # Unknown profile id, and no payload: plain welcome, no button.
    upd2 = fake_update(333, "Carol")
    asyncio.run(bot_mod.start_handler(
        upd2, SimpleNamespace(args=["profile_999999"])))
    assert not any("profile_" in (u or "")
                   for (_, u) in profile_buttons(upd2.message.replies[0][1]))
    upd3 = fake_update(333, "Carol")
    asyncio.run(bot_mod.start_handler(upd3, SimpleNamespace(args=[])))
    assert not any("profile_" in (u or "")
                   for (_, u) in profile_buttons(upd3.message.replies[0][1]))
    print("bot /start without a valid profile: no profile button OK")

    # Client: sidebar item, view, loaders, routing, earlier phases.
    html = c.get("/webapp/").text
    assert 'data-go="qr"' in html and "My QR" in html, "sidebar item gone"
    assert 'id="view-qr"' in html and 'id="qr-box"' in html, "view gone"
    js = c.get("/webapp/app.js").text
    assert "async function loadMyQr()" in js, "loadMyQr gone"
    assert "async function downloadQr(btn, qrUrl)" in js, "downloadQr gone"
    assert "function routeStartParam()" in js, "routeStartParam gone"
    assert "function bootOk()" in js, "bootOk gone"
    assert "showTaskAd" in js, "Phase 113 wiring gone"
    assert "openPhotoViewer" in js, "Phase 112 wiring gone"
    css = c.get("/webapp/style.css").text
    assert ".qr-card" in css and ".qr-img" in css, "QR CSS gone"
    for asset in ("style.css?v=115", "app.js?v=115", "games.js?v=115"):
        assert asset in html, asset
    print("client: sidebar, view, loaders, routing, ?v=115 OK")

print("PHASE 114 OK")
