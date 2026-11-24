"""Phase-155 tests, CONVERTED in Phase 156 to a removal guard.

Phase 155 shipped the mascot as a vendored image
(webapp/assets/mascot-head.webp, 48 px button). Phase 156 (owner order
Nov 20, 2026) replaced it with a REAL 3D head (Three.js, no image) and
a 40 px button. This suite now guards the removal: the image file and
every reference to it must be gone, and the 3D canvas + vendored
Three.js must be in their place. The 3D behaviour itself is covered
in depth by test_phase156.py.
"""
import os

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

# 1. The image is gone — file, markup, styles and code.
assert not os.path.exists("webapp/assets/mascot-head.webp")
assert "mascot-head" not in HTML
assert "mascot-head" not in JS
assert "mascot-head" not in CSS
wrap = HTML[HTML.index('id="mascot-wrap"'):]
wrap = wrap[:wrap.index("</div>\n</div>") + len("</div>\n</div>")]
assert "<img" not in wrap, "mascot button must not contain an <img>"

# 2. The 3D replacement is in place.
assert 'id="mascot-canvas"' in HTML
assert 'id="mascot-fallback"' in HTML
assert "vendor/three/three.min.js?v=173" in HTML
assert os.path.exists("webapp/vendor/three/three.min.js")
assert os.path.getsize("webapp/vendor/three/three.min.js") > 500 * 1024
assert "Phase 156" in HTML and "Phase 156" in JS and "Phase 156" in CSS
assert "Phase 155" not in HTML and "Phase 155" not in JS \
    and "Phase 155" not in CSS

# 3. Version.
assert HTML.count("?v=173") == 10, HTML.count("?v=173")
assert "?v=15" + "5" not in HTML

print("PHASE 155 (removal guard) OK")
