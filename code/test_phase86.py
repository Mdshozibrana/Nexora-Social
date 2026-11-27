"""Phase-86 tests — CONVERTED by Phase 152 (owner order Nov 20, 2026)
into a removal guard, then CONVERTED AGAIN by Phase 201 (owner
order Nov 27, 2026): the Museum is BACK as a new 3D-walkthrough
feature, so the guards below prove the NEW Museum is present and
only the OLD implementation is gone. The Design gallery (whose
pictures the Museum re-displayed) stays exactly as it is.
"""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()

# Phase 201: the Museum is present in every client file; the bot
# has no museum code (client-only feature), so that guard stays.
assert "museum" in HTML.lower(), "museum missing from index.html"
assert "museum" in JS.lower(), "museum missing from app.js"
assert "museum" in CSS.lower(), "museum missing from style.css"
assert "museum" not in BOT.lower(), "museum in bot.py"
# Specifically: section, sidebar button, showView entry present.
assert 'data-go="museum"' in HTML
assert '<section id="view-museum"' in HTML
assert '"nearby", "qr", "trending", "settings", "blood", "skills", "museum"]' in JS
assert "openMuseum" in JS and "reloadMuseum" in JS
assert "MUSEUM_THEMES" not in JS and "museumZoom" not in JS
# Neighbours that shared the Museum's space are intact.
assert 'data-go="blood"' in HTML and 'id="view-blood"' in HTML
assert 'data-go="designs"' in HTML and 'id="view-designs"' in HTML
assert "loadDesigns" in JS and "design-grid" in HTML
assert "app.js?v=201" in HTML and "style.css?v=201" in HTML
print("PHASE 86 OK (new Museum present, old Museum gone, neighbours intact)")
