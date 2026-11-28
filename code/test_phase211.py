"""Phase 211 tests: tapping a design opened a DIFFERENT design the
first time (owner report Nov 28, 16:54 Dhaka).

Two root causes, both proven by the Node harness
(nexora_designs/phase211_design_proof.js), which FAILS exactly 5
checks on the pre-patch code and passes all 36 on the new code:
(A) Stale sheet image — closeDesignSheet() never cleared
    dsImg.src, so the next open showed the PREVIOUS design's image
    until the new full-size file arrived (prompt/text already from
    the tapped design). The user literally saw another design.
(B) Masonry tap mis-target — the gallery is a 2-column CSS
    masonry whose cards grow as their images load (only min-height
    180px is reserved), so the card under a stationary finger can
    change between pointerdown and click, and the tap opens the
    WRONG design.
Fix: close clears the sheet image; the sheet loads the 480px thumb
first (already cached from the grid — the tapped design shows
instantly) and swaps in the full size when its preload arrives,
guarded so a stale preload never overwrites a newer design; the
click opens the design the finger pressed (designPressed), in the
gallery card and in the related strip alike. Phase 189 retry /
failed-state behaviour and Phase 202 image-only cards are intact.
Client-only: no new routes, no schema change. Plain script (run.sh
runs it directly).
"""
import os
import subprocess

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = (
    "sqlite:///" + os.path.expanduser(
        "~/workspace/nexora_run69/test_phase211.sqlite"))
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES, _health_version  # noqa: E402

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
DESIGNS = os.path.expanduser("~/workspace/nexora_designs")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
CSS = open(os.path.join(ROOT, "code/webapp/style.css")).read()
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
c = TestClient(app)

# --- 1. JS parses (node) ------------------------------------------
for f in ("webapp/app.js", "webapp/games.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True,
                       cwd=os.path.join(ROOT, "code"))
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (app.js + games.js parse)")

# --- 2. Node harness: the real app.js, both root causes. ----------
r = subprocess.run(
    ["node", os.path.join(DESIGNS, "phase211_design_proof.js"),
     os.path.join(ROOT, "code/webapp/app.js")],
    capture_output=True, text=True, timeout=60)
assert r.returncode == 0, r.stdout + r.stderr
assert "DONE failures=0" in r.stdout, r.stdout
for line in (
        "tap opens the PRESSED design C, not the hit-tested A",
        "close clears the sheet image (no stale A)",
        "opening B never shows the previous design A",
        "sheet loads the thumb first (instant correct image)",
        "related tap opens the pressed design R2",
        "long-press swallows the tap (no sheet opens)",
        "like tap opens no sheet"):
    assert line in r.stdout, (line, r.stdout)
print("design harness OK (36/36: stale sheet + mis-target + regressions)")

# --- 3. Client markers --------------------------------------------
assert "let designPressed = null;" in JS
assert "let dsFullSeq = 0;" in JS
# Sheet: thumb first, then the guarded full-size preload.
assert 'dsImg.src = mediaUrl(d.image_file_id, {thumb: true});' in JS
assert "const full = new Image();" in JS
assert "if (fullToken !== dsFullSeq || !currentDesign ||" in JS
assert "dsImg.src = mediaUrl(d.image_file_id);" in JS
# Close: the sheet image is cleared, preloads invalidated.
oi = JS.index("function closeDesignSheet() {")
ci = JS.index("\n}", oi)
assert 'dsImg.removeAttribute("src");' in JS[oi:ci], JS[oi:ci]
assert "dsFullSeq++;" in JS[oi:ci]
# Gallery card + related strip: the click opens the pressed design.
assert 'el.addEventListener("pointerdown", () => { designPressed = d; });' in JS
assert "openDesignSheet(designPressed || d); designPressed = null; };" in JS
assert 'card.addEventListener("pointerdown", () => { designPressed = rel; });' in JS
assert "openDesignSheet(designPressed || rel); designPressed = null; };" in JS
# The pressed target is dropped when a grid/strip rebuilds.
assert JS.count("designPressed = null;") >= 3, JS.count("designPressed = null;")
print("client markers OK (thumb-first sheet + pressed-design taps)")

# --- 4. Neighbours intact -----------------------------------------
# Phase 189: eager + retry + failed-state clearing, sheet wiring.
at = JS.index("function designCard(d)")
block = JS[at:at + 4600]
assert 'img.loading = "eager"' in block, "card img is not eager"
assert 'media.append(img, shield, retry)' in block, "no retry in card"
assert 'img.onload = () => media.classList.remove("design-img-failed")' in block
assert JS.count('img.loading = "eager"') == 2, JS.count('img.loading = "eager"')
assert JS.count('img.loading = "lazy"') == 5, JS.count('img.loading = "lazy"')
assert 'delete dsImg.dataset.mtok; delete dsImg.dataset.mr;' in JS
assert '$("ds-retry").onclick = () => retryDesignImg($("ds-img"));' in JS
assert '$("ds-img").onload = () => {' in JS
assert ".design-media { position: relative; min-height: 180px;" in CSS
# Phase 202: grid cards stay image-only; the sheet keeps full size.
assert "design-card-body" not in block, "grid card regained a body"
assert 'img.src = mediaUrl(d.image_file_id, {thumb: true});' in block
# Phase 108/109/110: sheet open/close still lock the shell + reset.
oi = JS.index("function openDesignSheet(d) {")
ci = JS.index("function closeDesignSheet() {")
assert '$("app-scroll").classList.add("sheet-open")' in JS[oi:ci]
assert '$("ds-download").textContent = "⬇️ Download"' in JS[oi:ci]
end = JS.index("\n}", ci)
assert '$("app-scroll").classList.remove("sheet-open")' in JS[ci:end]
# Phase 99/115: tap still opens the sheet (literals carry the
# pressed-design capture now — see phase211_fix_tests.py).
assert "attachLongPress(el, () => showDesignPop(d, el));" in JS
assert "openDesignSheet(designPressed || rel)" in JS
assert "#design-grid, .design-grid { columns: 2; column-gap: 10px; }" in CSS
print("neighbours OK (189/202/108/109/110/99/115)")

# --- 5. Version pins + routes + backup + health. ------------------
assert HTML.count("?v=211") == 10, HTML.count("?v=211")
assert "?v=21" + "0" not in HTML
assert "app.js?v=211" in HTML and "games.js?v=211" in HTML
assert "style.css?v=211" in HTML
assert 'menu_url.rstrip("/") + "/?v=211"' in BOT
assert ("/?v=21" + "0") not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 196, len(paths)
assert len(_BACKUP_TABLES) == 55, len(_BACKUP_TABLES)
assert _health_version() == 211, _health_version()
print("5. version ?v=211, routes 196, backup 55, health 211 OK")

# --- 6. Served assets carry the fix. ------------------------------
html = c.get("/webapp/").text
assert html.count("?v=211") == 10, html.count("?v=211")
assert ("?v=21" + "0") not in html
served_js = c.get("/webapp/app.js").text
for marker in ("let designPressed = null;", "let dsFullSeq = 0;",
               "dsImg.src = mediaUrl(d.image_file_id, {thumb: true});",
               "const full = new Image();",
               'dsImg.removeAttribute("src");'):
    assert marker in served_js, marker
print("6. served shell + app.js carry the Phase 211 fix OK")

print("PHASE 211 OK")
