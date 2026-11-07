"""Phase-67 tests: holding a design no longer summons Telegram's
native image menu (owner's screenshot: our popup appeared AND
Telegram's own sheet with the raw /media URL — Open in… /
Download / Copy Link).

That menu is the WebView's image hit-test: a hold landing on an
<img> is treated as an image hold at the app level, which a JS
contextmenu preventDefault cannot reliably stop. The fix puts a
transparent shield div over every design image, so the touch
lands on a plain element: gallery cards build image + shield in a
.design-media wrapper, the detail sheet wraps #ds-img the same
way, and the sheet's long-press target moves from the <img> to
the wrapper. Images are also marked not-draggable.
"""
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()

# gallery card: media wrapper + shield around the image
at = JS.index("function designCard(d)")
block = JS[at:at + 2600]  # widened in Phase 99: designCard grew
assert 'media.className = "design-media"' in block
assert 'shield.className = "img-shield"' in block
assert "media.append(img, shield)" in block
assert "el.append(media, body)" in block
assert "img.draggable = false" in block
print("card shield OK")

# detail sheet: wrapped image in the markup, wrapper is the
# long-press anchor and target
assert 'id="ds-media"' in HTML
assert HTML.index('id="ds-media"') < HTML.index('id="ds-img"')
assert '<div class="img-shield"></div>' in HTML
assert 'attachLongPress($("ds-media")' in JS
assert 'showDesignPop(currentDesign, $("ds-media"))' in JS
assert 'attachLongPress($("ds-img")' not in JS
print("sheet shield OK")

# CSS: the shield covers the image and sits above it
assert ".design-media { position: relative; }" in CSS
shield_rule = CSS[CSS.index(".img-shield {"):CSS.index(".img-shield {") + 120]
assert "position: absolute" in shield_rule and "inset: 0" in shield_rule
print("shield CSS OK")

print("PHASE 67 OK")
