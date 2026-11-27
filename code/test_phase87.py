"""Phase-87 tests — CONVERTED by Phase 152 (owner order Nov 20, 2026)
into a removal guard, then CONVERTED AGAIN by Phase 201 (owner
order Nov 27, 2026): the Museum is BACK as a new 3D-walkthrough
feature. Guard: none of the OLD Museum's pieces remain — no zoom
state, no house plan, no stage, no themes — while the new
openMuseum/reloadMuseum entry points exist. The Design gallery
it re-displayed is untouched.
"""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

for bit in ("museumZ", "museumZoom", "paintMuseumPlan", "MUSEUM_THEMES",
            "museumSetX", "museumMoved",
            "museum-plan", "museum-zoom", "museum-stage", "museum-room",
            "museum-name", "museum-empty", "museum-hint", "mfadein",
            "plan-room", "m-wall", "m-door", "mframe", ".mplate"):
    # ".mplate" with the dot: bare "mplate" is a substring of
    # "grid-template" in unrelated CSS, so it must not be asserted bare.
    assert bit not in JS, bit
    assert bit not in CSS, bit
    assert bit not in HTML, bit
assert "museum" in HTML.lower()
assert "museum" in JS.lower()
assert "museum" in CSS.lower()
assert "openMuseum" in JS and "reloadMuseum" in JS
# Design gallery (the Museum's picture source) still works.
assert "loadDesigns" in JS and "design-grid" in HTML
assert "openDesignSheet" in JS
assert "app.js?v=202" in HTML and "style.css?v=202" in HTML
print("PHASE 87 OK (old Museum zoom/rooms gone, new Museum present)")
