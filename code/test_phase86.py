"""Phase-86 tests — CONVERTED by Phase 152 (owner order Nov 20, 2026):
the Museum section is REMOVED entirely ("Museum এই সেকশনটা
রিমুভ করো, লাগবে না"). This suite is kept as a removal guard:
it proves Museum is gone instead of being deleted — a deleted
suite leaves no proof. The Design gallery (whose pictures the
Museum re-displayed) stays exactly as it is.
"""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()

# Museum is gone from every client file and the server.
assert "museum" not in HTML.lower(), "museum in index.html"
assert "museum" not in JS.lower(), "museum in app.js"
assert "museum" not in CSS.lower(), "museum in style.css"
assert "museum" not in BOT.lower(), "museum in bot.py"
# Specifically: no section, no sidebar button, no showView entry.
assert 'data-go="museum"' not in HTML
assert '<section id="view-museum"' not in HTML
assert '"nearby", "qr", "trending", "settings", "blood", "skills"]' in JS
assert "openMuseum" not in JS and "loadMuseum" not in JS
# Neighbours that shared the Museum's space are intact.
assert 'data-go="blood"' in HTML and 'id="view-blood"' in HTML
assert 'data-go="designs"' in HTML and 'id="view-designs"' in HTML
assert "loadDesigns" in JS and "design-grid" in HTML
assert "app.js?v=181" in HTML and "style.css?v=181" in HTML
print("PHASE 86 REMOVAL GUARD OK (Museum gone, neighbours intact)")
