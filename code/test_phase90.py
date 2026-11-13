"""Phase-90 tests: theme shades in the Me section (owner).

Every member gets a Theme Colours card on their own
profile: the 15 palettes from the owner's screenshots.
One shade can dress the whole app, or shades can be
assigned per zone (background / cards / accent). The
derivation guarantees readable text — ink is darkened
until it clears 7:1 against the card colour, dim text
4.2:1, accent text 4.5:1, and button text picks the
better of white / near-black on the gradient. All 15
palettes were proven contrast-safe in a node harness
against the shipped engine before this phase shipped.
With nothing picked, no data-theme attribute is set and
the clay default is untouched.
"""
HTML = open("webapp/index.html").read()
APP = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
MAIN = open("app/main.py").read()

# all fifteen palettes, with the owner's exact hexes
assert "THEME_PALETTES" in APP
for name in ("Navy Mirage", "Emerald Depth", "Obsidian Plum",
             "Walnut Noir", "Crimson Velvet", "Marple", "Sunset",
             "Forest Mist", "Berry Rose", "Terracotta",
             "Copper Bordeaux", "Mustard Anthracite", "Sage Cream",
             "Rose Olive", "Lavender Beige"):
    assert name in APP, name
for hexv in ("#141E30", "#35577D", "#0F2027", "#28623A",
             "#2D1E2F", "#4E2A4F", "#CA2851", "#EA6113",
             "#051F20", "#DAF1DE", "#A3B18A", "#F2E8CF",
             "#C29A2E", "#FAF3D6", "#FAE3EC", "#8F2D35"):
    assert hexv in APP, hexv
# the engine: derivation with its contrast floors
for bit in ("deriveTheme", "thContrast(ink, card) < 7",
            "thContrast(dim, card) < 4.2",
            "thContrast(accText, card) < 4.5",
            "thLum(card) < 0.72"):
    assert bit in APP, bit
# zones, persistence, boot application
for bit in ("nx_theme", "applyUserTheme", '"bg"', '"card"',
            '"accent"', "themeState.picks", "dataset.theme"):
    assert bit in APP, bit
# the picker card lives in the own-profile extras
for bit in ("themeCard()", "🎨 Theme Colours", "theme-drop",
            "theme-where", "wrap.appendChild(themeCard())"):
    assert bit in APP, bit
# the override layer re-skins the app only under data-theme
for bit in ("html[data-theme] body", "html[data-theme] #nav-pill",
            "html[data-theme] .hero", "html[data-theme] #glassbar",
            "html[data-theme] #design-post", "--t-acc1", "--t-onacc",
            ".theme-drop-list", ".theme-strip"):
    assert bit in CSS, bit
# Nexa can explain the feature
assert "THEME COLOURS" in MAIN and "never blend" in MAIN
assert "app.js?v=114" in HTML and "games.js?v=114" in HTML
print("PHASE 90 OK")
