"""Phase-49 tests: link preview (owner) — when the Nexora
link is shared, chat apps build the preview card from these
Open Graph tags and the 1200x630 image that ships with the
webapp (served statically at /webapp/og-image.png)."""
import os

from PIL import Image

HTML = open("webapp/index.html").read()
for marker in ('property="og:title"',
               'property="og:description"',
               'property="og:image"',
               "https://nexora-9pip.onrender.com/webapp/og-image.png",
               'name="twitter:card" content="summary_large_image"',
               'name="description"'):
    assert marker in HTML, marker
print("preview tags OK")

path = os.path.join("webapp", "og-image.png")
assert os.path.exists(path)
im = Image.open(path)
assert im.size == (1200, 630), im.size
print("preview image OK (1200x630)")

print("PHASE-49 TESTS PASSED")
