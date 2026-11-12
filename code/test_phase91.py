"""Phase-91 tests: the shade picker becomes a dropdown
(owner, from his screenshot of the live picker: tidy the
shades up and make them a dropdown).

The fifteen palette cards that filled the whole profile
are now one dropdown: a button showing the current shade
for the chosen zone, a neat scrollable list of compact
rows (strip + name + where-applied ticks), a pick applies
at once and closes the list, and a "Now:" line under it
summarises which shade dresses each zone. Zones, reset,
the contrast-safe engine and persistence are unchanged
from Phase 90.
"""
HTML = open("webapp/index.html").read()
APP = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

# dropdown machinery in the picker
for bit in ("themeDropOpen", "theme-drop-btn", "theme-drop-list",
            "theme-drop-item", "Choose a shade",
            '"Now: Background "'):
    assert bit in APP, bit
# picking from the list applies and closes it
assert "themeDropOpen = false;\n        saveTheme(); applyUserTheme();" in APP
# the old full grid is gone
assert "theme-grid" not in APP and "theme-pal" not in APP
# tidy dropdown styling, overlaying with its own surface
for bit in (".theme-drop {", ".theme-drop-btn", ".theme-drop-list",
            ".theme-drop-item", ".theme-now",
            "max-height: 264px", "position: absolute"):
    assert bit in CSS, bit
assert ".theme-grid" not in CSS
assert "app.js?v=104" in HTML and "games.js?v=104" in HTML
print("PHASE 91 OK")
