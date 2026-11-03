"""Phase-70 tests: the app-wide long-press shield (owner: "বটের
যেকোনো পেজে কোথাও যেনো চাপ দিয়ে ধরলে Render এর কোনো লিংক শো
না করে").

Phase 67 shielded design images only. A hold anywhere else —
feed photos, videos, buttons, text — could still raise the
Telegram WebView's native menu, which displays the raw hosting
(Render) URL. Now: CSS kills the touch callout and text
selection app-wide (inputs/textareas keep selection so paste
works), images can't be dragged, and a capture-phase
contextmenu listener swallows the event everywhere except
inside text fields. The design long-press (pointer-based) and
the Phase 67 shields are untouched and keep working.
"""
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()
JS = open("webapp/app.js").read()

# CSS shield
for bit in ("-webkit-touch-callout: none",
            "body { -webkit-user-select: none; user-select: none; }",
            "input, textarea { -webkit-user-select: text; "
            "user-select: text; }",
            "img { -webkit-user-drag: none; }"):
    assert bit in CSS, bit
print("css shield OK")

# JS guards (capture phase, text-field exemption)
seg = JS[JS.index("Phase 70: no long-press"):]
for bit in ('document.addEventListener("contextmenu"',
            't.tagName === "INPUT"',
            't.tagName === "TEXTAREA"',
            "e.preventDefault();",
            'document.addEventListener("dragstart"',
            'e.target.tagName === "IMG"'):
    assert bit in seg, bit
assert seg.index('addEventListener("contextmenu"') < seg.index(
    'addEventListener("dragstart"')
print("js guards OK")

# Phase 67 design shield survives beside the global one
assert ".img-shield" in CSS
assert "attachLongPress" in JS
print("phase-67 shield intact")

assert "style.css?v=76" in HTML and "app.js?v=76" in HTML \
    and "games.js?v=76" in HTML
print("asset pins OK")

print("PHASE 70 OK")
