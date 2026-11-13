"""Phase-112 tests: FULL-SCREEN PROFILE PHOTO VIEWER (owner, Nov 13).

Owner request (Bengali): tap a user's profile picture and it opens
big — full-screen, full view.

Fix: avatarEl wires EVERY photo avatar (profile hero, post cards,
comments, leaderboard, messages, notifications — one factory) to
openPhotoViewer. The viewer is a topmost fixed overlay (z-index 100)
with the photo shown whole (object-fit contain, never cropped), the
member's name below, and ✕ top-right; tap anywhere, ✕, or the app
back button closes it. A tap stops propagation so the parent's
open-profile / open-chat action does not fire; pointerdown/up stop
propagation (Phase 99 pattern) so a hold on the avatar never arms a
parent card's long-press menu. Initials avatars (no photo) stay
unclickable — there is nothing to show.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase112.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as c:
    html = c.get("/webapp/").text
    # Viewer shell at body level, hidden by default.
    assert 'id="photo-viewer" hidden' in html, "viewer shell gone"
    assert 'id="pv-img"' in html, "viewer img gone"
    assert 'id="pv-name"' in html, "viewer name gone"
    assert 'id="pv-close"' in html, "viewer close gone"
    print("viewer shell OK")

    css = c.get("/webapp/style.css").text
    # Topmost fixed overlay, dark backdrop, photo whole not cropped.
    vi = css.index("#photo-viewer {")
    vcss = css[vi:vi + 400]
    assert "position: fixed" in vcss, vcss
    assert "z-index: 100" in vcss, vcss
    assert "#photo-viewer[hidden] { display: none; }" in css
    assert "object-fit: contain" in css, "photo may crop"
    assert "max-width: 100%" in css and "max-height: 100%" in css
    assert "img.avatar { cursor: pointer; }" in css
    print("viewer CSS OK")

    js = c.get("/webapp/app.js").text
    # avatarEl: photo avatars open the viewer; taps and holds do not
    # leak to the parent card.
    ai = js.index("function avatarEl(")
    ab = js[ai:js.index("// ---------- Phase 112", ai)]
    assert "openPhotoViewer(photoId, name)" in ab, ab
    assert "e.stopPropagation();" in ab, ab
    assert '"pointerdown", e => e.stopPropagation()' in ab, ab
    assert '"pointerup", e => e.stopPropagation()' in ab, ab
    assert "img.draggable = false;" in ab, ab
    print("avatarEl wiring OK")

    # Viewer open/close + wiring.
    oi = js.index("function openPhotoViewer(")
    ob = js[oi:js.index("// ---------------------------------------------------------------- posts", oi)]
    assert '$("pv-img").src = mediaUrl(photoId);' in ob, ob
    assert '$("pv-name").textContent = name || "";' in ob, ob
    assert '$("photo-viewer").hidden = false;' in ob, ob
    assert "function closePhotoViewer()" in ob, ob
    assert '$("pv-img").src = "";' in ob, ob
    assert '$("photo-viewer").onclick = () => closePhotoViewer();' in ob
    assert '$("pv-close").onclick' in ob, ob
    print("viewer open/close OK")

    # Back button: shows while the viewer is open, closes it first.
    assert '|| !$("photo-viewer").hidden' in js, "overlay check gone"
    bi = js.index("function onAppBack()")
    bb = js[bi:bi + 500]
    assert 'if (!$("photo-viewer").hidden) closePhotoViewer();' in bb, bb
    print("back-button wiring OK")

    # Phase 108/109/110/111 survive.
    assert "#app-scroll.sheet-open" in css, "Phase 108 lock gone"
    assert 'id="ds-download"' in html, "Phase 109 button gone"
    assert "tg.downloadFile" in js, "Phase 110 wiring gone"
    main = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "app", "main.py")).read()
    assert 'headers["cache-control"] = "private, max-age=604800' in main, \
        "Phase 111 cache gone"
    print("Phase 108/109/110/111 markers OK")

    for asset in ("style.css?v=116", "app.js?v=116", "games.js?v=116"):
        assert asset in html, asset
    print("asset version ?v=116 OK")

print("PHASE 112 OK")
