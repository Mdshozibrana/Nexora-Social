"""Phase-86 tests: the Museum (owner: a Museum section in the
sidebar — many rooms, each with its own design, pictures on
the walls; drag or scroll to walk along a room, doors lead to
the next room).

Client-only: the exhibits are the Design gallery's pictures
(GET /designs), five per room, each room wearing the next of
six themes. Tapping a picture opens its design sheet.
"""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

# sidebar entry + view wiring
assert 'data-go="museum"' in HTML and "🏛️" in HTML
assert '<section id="view-museum" hidden>' in HTML
assert '"nearby", "museum", "qr"]' in JS
assert 'if (name === "museum") openMuseum();' in JS
assert "museum: () => loadMuseum(true)," in JS
# data source + room building
assert "MUSEUM_THEMES" in JS
for name in ("Rose Hall", "Midnight Gallery", "Emerald Room",
             "Sky Gallery", "Sunset Salon", "Marble Hall"):
    assert name in JS, name
assert 'api("/designs?limit=40")' in JS
assert "i += 5" in JS  # five exhibits per room
assert "openMuseumRoom" in JS and "paintMuseumPlan" in JS
assert "openDesignSheet(d)" in JS  # tap a picture -> its sheet
assert "mediaUrl(d.image_file_id)" in JS
# walking: drag + wheel pan, drag-vs-tap guard, PTR guard
assert '"pointerdown"' in JS and '"pointermove"' in JS
assert "museumSetX" in JS and "translateX(" in JS
assert "museumMoved < 8" in JS
assert 'addEventListener("wheel"' in JS
assert 'museum-stage' in JS and "stopPropagation" in JS
# stage + theme pieces in markup/CSS
for bit in ('id="museum-stage"', 'id="museum-room"',
            'id="museum-rooms"', 'id="museum-name"',
            'id="museum-empty"'):
    assert bit in HTML, bit
for bit in ("#museum-stage", ".m-wall", ".m-floor", ".m-spot",
            ".mframe", ".mplate", ".m-bench", ".m-door",
            ".plan-room.on", "--m-frame", "touch-action: none",
            "@keyframes mfadein"):
    assert bit in CSS, bit
assert "app.js?v=114" in HTML and "style.css?v=114" in HTML
print("PHASE 86 OK")
