"""Phase-87 tests: Museum zoom + a whole house of rooms
(owner: the museum must zoom in and out, and be a whole
house with many rooms).

Zoom: + / − buttons with a % readout (tap it to reset), a
two-finger pinch, double-tap toggle, and Ctrl+scroll. Rooms:
the fetch now follows the cursor once (up to 80 exhibits =
16 rooms), twelve themes cycle, and the room list is drawn
as a house plan you tap to enter a room.
"""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

# twelve themes now — the new house rooms included
for name in ("Living Lounge", "The Library", "Studio Loft",
             "Garden Room", "Attic Gallery", "Terrace Hall"):
    assert name in JS, name
# up to two pages of exhibits
assert 'api("/designs?limit=40")' in JS
assert "r.next_cursor" in JS and "&cursor=" in JS
# house plan navigation
assert "paintMuseumPlan" in JS
assert 'class="museum-plan"' in HTML
assert "House plan" in HTML
for bit in (".museum-plan", ".plan-room", ".plan-room.on",
            ".plan-name", ".plan-count"):
    assert bit in CSS, bit
# zoom: state, machinery, controls
assert "museumZ = 1" in JS and "museumZoom" in JS
assert "Math.min(2.5" in JS
assert 'id="museum-zin"' in HTML and 'id="museum-zout"' in HTML
assert 'id="museum-zlabel"' in HTML
assert '$("museum-zin").onclick' in JS
assert '$("museum-zlabel").onclick' in JS
assert '"dblclick"' in JS
assert "e.ctrlKey" in JS and "pinch" in JS
assert "transform-origin: 0 50%" in CSS
assert ".museum-zoom" in CSS
# room switches reset the zoom
assert "museumZ = 1;\n  museumSetX(0);" in JS
assert "app.js?v=95" in HTML and "style.css?v=95" in HTML
print("PHASE 87 OK")
