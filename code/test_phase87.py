"""Phase-87 tests — CONVERTED by Phase 152 (owner order Nov 20, 2026):
the Museum (zoom + a whole house of rooms) is REMOVED entirely.
Guard: none of its pieces remain — no zoom state, no house plan,
no stage, no themes. The Design gallery it re-displayed is
untouched.
"""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

for bit in ("museumZ", "museumZoom", "paintMuseumPlan", "MUSEUM_THEMES",
            "openMuseum", "loadMuseum", "museumSetX", "museumMoved",
            "museum-plan", "museum-zoom", "museum-stage", "museum-room",
            "museum-name", "museum-empty", "museum-hint", "mfadein",
            "plan-room", "m-wall", "m-door", "mframe", ".mplate"):
    # ".mplate" with the dot: bare "mplate" is a substring of
    # "grid-template" in unrelated CSS, so it must not be asserted bare.
    assert bit not in JS, bit
    assert bit not in CSS, bit
    assert bit not in HTML, bit
assert "museum" not in HTML.lower()
assert "museum" not in JS.lower()
assert "museum" not in CSS.lower()
# Design gallery (the Museum's picture source) still works.
assert "loadDesigns" in JS and "design-grid" in HTML
assert "openDesignSheet" in JS
assert "app.js?v=198" in HTML and "style.css?v=198" in HTML
print("PHASE 87 REMOVAL GUARD OK (Museum zoom/rooms gone)")
