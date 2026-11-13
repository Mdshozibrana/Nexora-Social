"""Phase-109 tests: DESIGN SHEET DOWNLOAD BUTTON (owner, Nov 13).

Owner request: in the Design sheet, like Copy Prompt, the user
should be able to download the design image. A Download button
sits in the sheet's action row next to Copy Prompt and uses the
same anchor-download pattern as the post options Download
(Phase 54): an <a> to mediaUrl(design image_file_id) with a
download attribute, clicked programmatically.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase109.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as c:
    html = c.get("/webapp/").text
    # The button exists in the sheet's action row, right after
    # Copy Prompt.
    ci = html.index('id="ds-copy"')
    di = html.index('id="ds-download"')
    assert di > ci, "Download must sit next to Copy Prompt"
    assert "⬇️ Download" in html[di:di + 60], "button label"
    # It lives inside the sheet's action row.
    assert html.index("ds-actions") < di, "button outside .ds-actions"
    print("Download button in sheet OK")

    js = c.get("/webapp/app.js").text
    hi = js.index('$("ds-download").onclick')
    handler = js[hi:js.index("\n};", hi)]
    assert "mediaUrl(currentDesign.image_file_id)" in handler, handler
    assert 'a.download = "";' in handler, handler
    assert "a.click();" in handler, handler
    print("Download wiring OK")

    # Phase 108 survives: the scroll lock is still wired.
    css = c.get("/webapp/style.css").text
    assert "#app-scroll.sheet-open" in css, "Phase 108 lock rule gone"
    assert "overscroll-behavior: contain;" in css
    oi = js.index("function openDesignSheet(d) {")
    ci2 = js.index("function closeDesignSheet() {")
    assert 'classList.add("sheet-open")' in js[oi:ci2]
    print("Phase 108 markers OK")

    for asset in ("style.css?v=116", "app.js?v=116", "games.js?v=116"):
        assert asset in html, asset
    print("asset version ?v=116 OK")

print("PHASE 109 OK")
