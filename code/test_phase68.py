"""Phase-68 tests: the popup icons become proper round Pinterest-
style buttons (owner: "আইকনগুলো কি রাউন্ড করা যায় না?").

On his Samsung the emoji glyphs rendered as chunky coloured
shapes (blue magnifier, ORANGE chat bubble on the green button,
red share tray) — nothing like the reference's uniform white
icons on dark round discs. The four buttons now carry inline
white line SVGs (magnifier, chat bubble, share nodes, pin) drawn
for this — verified by rasterising them — on a 48px circle with
a white ring, padding reset and flex:none so nothing in the clay
theme can squash them out of round.
"""
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()

seg = HTML[HTML.index('id="design-pop"'):HTML.index('id="design-pop"') + 2600]
assert seg.count("<svg") == 4, seg.count("<svg")
for btn in ("dp-similar", "dp-wa", "dp-share", "dp-save"):
    assert btn in seg
for emoji in ("🔍", "💬", "📤", "📌"):
    assert emoji not in seg, emoji
print("white SVG icons OK")

rule = CSS[CSS.index(".dp-btn {"):CSS.index(".dp-btn {") + 430]
for bit in ("width: 48px", "height: 48px", "border-radius: 50%",
            "padding: 0", "flex: none",
            "border: 2px solid rgba(255, 255, 255, .9)"):
    assert bit in rule, bit
assert ".dp-btn svg { width: 24px; height: 24px;" in CSS
print("round button CSS OK")

print("PHASE 68 OK")
