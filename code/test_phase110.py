"""Phase-110 tests: DESIGN DOWNLOAD VIA TELEGRAM downloadFile
(owner, Nov 13).

Owner report (from his phone, after Phase 109 went live): the
Download button does nothing, and he wants a visible sign when
a download has finished. Cause: a plain <a download> click is
silently ignored inside the Telegram WebView — the client never
starts a download there.

Fix: the handler now calls Telegram's native downloadFile
(WebApp 8.0+, verified against the real telegram-web-app.js:
params {url, file_name}, callback receives isDownloading) —
the client shows its own download popup and reports back.
The button shows Downloading… while it runs, ✅ Downloaded!
+ a status line when the client confirms the download, and
reverts to Download after 4s (or on cancel). Fallbacks: openLink
on old Telegram clients, the anchor on desktop browsers. The
file extension comes from a HEAD read of the /media
content-type (jpg/png/webp/gif, jpg fallback). Opening a design
resets the button label.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase110.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as c:
    js = c.get("/webapp/app.js").text
    hi = js.index('$("ds-download").onclick')
    handler = js[hi:js.index("\n};", hi)]
    # Native Telegram download first.
    assert "tg.downloadFile" in handler, handler
    assert "file_name" in handler, handler
    assert '"nexora-design-" + currentDesign.id' in handler, handler
    # Visible outcome on the button.
    assert '"⬇️ Downloading…"' in handler, handler
    assert '"✅ Downloaded!"' in handler, handler
    assert '"Download cancelled."' in handler, handler
    # Extension from the media content-type.
    assert 'method: "HEAD"' in handler, handler
    assert 'content-type' in handler, handler
    # Fallbacks: browser link, then the anchor.
    assert "tg.openLink" in handler, handler
    assert "a.click();" in handler, handler
    print("native download + feedback wiring OK")

    # Opening a design resets the label.
    oi = js.index("function openDesignSheet(d) {")
    ci = js.index("function closeDesignSheet() {")
    assert '$("ds-download").textContent = "⬇️ Download"' in js[oi:ci]
    print("openDesignSheet reset OK")

    html = c.get("/webapp/").text
    assert 'id="ds-download"' in html, "button gone"
    # Phase 108/109 survive.
    css = c.get("/webapp/style.css").text
    assert "#app-scroll.sheet-open" in css, "Phase 108 lock gone"
    print("Phase 108/109 markers OK")

    for asset in ("style.css?v=115", "app.js?v=115", "games.js?v=115"):
        assert asset in html, asset
    print("asset version ?v=115 OK")

print("PHASE 110 OK")
