"""Phase-108 tests: DESIGN SHEET SCROLL LOCK (owner, Nov 13).

Owner report (from his phone): opening a design from the Design
tab and scrolling moved the design grid behind the sheet. Cause:
the sheet is a fixed overlay, but the app's real scroller
(#app-scroll) stayed live, so every gesture on the sheet — or on
its backdrop — chained into the background grid (scroll chaining),
and the sheet's own edge scroll propagated too.

Fix: while the sheet is open, #app-scroll carries .sheet-open
(overflow hidden), added in openDesignSheet and removed in
closeDesignSheet (the single exit every close path uses). The
sheet itself also gets overscroll-behavior: contain, so its own
edge scroll never chains anywhere. The sheet keeps its own
overflow-y scroll.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase108.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as c:
    css = c.get("/webapp/style.css").text
    # The lock rule exists and hides the shell's overflow.
    lock = css[css.index("#app-scroll.sheet-open {"):]
    lock = lock[:lock.index("}")]
    assert "overflow: hidden;" in lock, lock
    # The sheet contains its own overscroll.
    sheet = css[css.index("#design-sheet {"):]
    sheet = sheet[:sheet.index("}")]
    assert "overscroll-behavior: contain;" in sheet, sheet
    # The shell itself still scrolls normally when unlocked.
    shell = css[css.index("#app-scroll { position: fixed;"):]
    shell = shell[:shell.index("}")]
    assert "overflow-y: auto;" in shell, shell
    # Neighbouring phases survive.
    assert ".profile-hero" in css, "Phase 105 hero gone"
    print("scroll-lock CSS OK")

    js = c.get("/webapp/app.js").text
    oi = js.index("function openDesignSheet(d) {")
    ci = js.index("function closeDesignSheet() {")
    assert '$("app-scroll").classList.add("sheet-open")' in js[oi:ci], \
        "openDesignSheet must lock the shell"
    end = js.index("\n}", ci)
    assert '$("app-scroll").classList.remove("sheet-open")' in js[ci:end], \
        "closeDesignSheet must unlock the shell"
    assert "nexora-backup" in js, "Phase 107 backup gone"
    print("open/close wiring OK")

    html = c.get("/webapp/").text
    for asset in ("style.css?v=117", "app.js?v=117", "games.js?v=117"):
        assert asset in html, asset
    print("asset version ?v=117 OK")

print("PHASE 108 OK")
