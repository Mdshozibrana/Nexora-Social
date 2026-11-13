"""Phase-92 tests: the shade dropdown learns to LOOK like
one (owner: "Drop Down বুঝা যাচ্ছে না" — users could not
tell the Phase-91 button was a dropdown).

The button is now an unmistakable select field: an inset
well holding a colour swatch, plain wording — "Choose
your shade" when nothing is picked for the zone, "Shade:
<name>" when one is — and a big filled circular chevron
badge that flips to ▲ while open. The zone chips gained
an "Apply the shade to:" label, and the open list starts
with a "🎨 Choose a shade" header and highlights the row
that is on the current zone. Everything else (engine,
zones, contrast floors, persistence) is Phase 90/91.
Verified headlessly with the real themeCard(): the
button invites a choice, opens to 15 rows under the
header, a pick applies/closes/saves, and the button
then reads "Shade: Navy Mirage".
"""
HTML = open("webapp/index.html").read()
APP = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

for bit in ("theme-drop-swatch", "theme-drop-text",
            "theme-drop-chev", '"Shade: " + cur.name',
            '"Choose your shade"', "Apply the shade to:",
            "theme-drop-head", '"🎨 Choose a shade"',
            "onThisZone"):
    assert bit in APP, bit
# the old ambiguous strip-button pieces are gone
assert "theme-caret" not in APP and "theme-caret" not in CSS
assert "Choose a shade…" not in APP
for bit in (".theme-drop-btn", ".theme-drop-swatch",
            ".theme-drop-chev", ".theme-drop-head",
            ".theme-drop-item.on", ".theme-label",
            "box-shadow: var(--clay-inset)"):
    assert bit in CSS, bit
assert "app.js?v=116" in HTML and "games.js?v=116" in HTML
print("PHASE 92 OK")
