"""Phase-79 tests: the sidebar reads clearly and sits on top
(owner screenshot + two complaints).

1) "যেটা সিলেক্ট করা হয়েছে সেই লেখাগুলো বুঝা যাচ্ছে না" —
   the selected item's word was invisible. Root cause: a
   legacy generic rule from the Telegram-theme era,
   `button.active { color: var(--tg-theme-button-text-color) }`
   (white), has specificity (0,1,1) and beat `.gb-item`'s plum
   (0,1,0), while `.gb-item.active`'s white pill (0,2,0) still
   won the background — white word on a white pill. The fix
   pins the plum on the active item and its label at (0,2,0)+.

2) "সাইডবার অন করার পরে সাইডবার পেজের নিচে পড়ে গেছে" — the
   open panel shared z-index 65 with the bottom nav and could
   run to the screen's bottom edge, so its lower rows slid
   behind the nav capsule. The panel and its backdrop now sit
   above the nav (80/79, below the design popup's 84/85), and
   the open panel's height ends above the nav; it scrolls
   internally, so every row stays reachable.
"""
CSS = open("webapp/style.css").read()
HTML = open("webapp/index.html").read()

# --- the selected word stays readable ----------------------------
seg = CSS[CSS.index(".gb-item.active {"):]
seg = seg[:seg.index("}")]
assert "color: #3A2E33" in seg, seg  # Phase 105: ink #472A3E -> #3A2E33
assert ".gb-item.active .gb-label { color: #3A2E33; }" in CSS
# the legacy leak itself is documented, not silently relied on
assert "button.active { background: var(--tg-theme-button-color" in CSS
print("active label colour OK")

# --- the sidebar layers above the page and clears the nav --------
assert "#glassbar { position: fixed; left: 8px; top: 50%; z-index: 80;" in CSS
assert "#gb-backdrop { position: fixed; inset: 0; z-index: 79;" in CSS
assert ".bottom-nav { z-index: 65; }" in CSS  # nav itself unchanged
assert "max-height: calc(100dvh - 116px)" in CSS
assert "max-height: calc(100vh - 20px)" not in CSS
# the panel still scrolls internally, so capped height loses nothing
assert "overflow-y: auto" in CSS
print("sidebar layering OK")

assert "app.js?v=117" in HTML and "style.css?v=117" in HTML
print("PHASE 79 OK")
