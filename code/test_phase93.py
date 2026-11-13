"""Phase-93 tests: eight more shades from the owner's
second batch (owner: add whichever is not already added;
skip what exists). None of the eight duplicated the first
fifteen, so the list grows 15 -> 23:

  Milk & Plum (#381932/#FFF3E6), Night & Kiwi
  (#222222/#89E900), Black & Gold (dopely wedding set of
  five), Peach Bloom (dopely peach set of five — Cocoa
  Detail's label was unreadable in the screenshot, so its
  hex #5C4034 was sampled from the card's own fill, the
  method validated against the set's labelled cards),
  Champagne & Slate (#5A5D64/#E7D28F), Cocoa & Cloud
  (#53332A/#B8CDE3), Meadow & Violet (#5E397F/#9FB354),
  Winter & Cherry (#C10015/#93B4D7).

All 23 palettes were re-run through the real deriveTheme
engine in a node harness: worst ink/card 7.02, dim 4.21,
accent-text 4.59 — every shade still honours the owner's
no-blend rule.
"""
import re

HTML = open("webapp/index.html").read()
APP = open("webapp/app.js").read()

block = APP[APP.index("const THEME_PALETTES"):APP.index("];", APP.index("const THEME_PALETTES"))]
ids = re.findall(r'id: "([a-z0-9-]+)"', block)
assert len(ids) == 33, ids  # 23 at Phase 93; 27 since Phase 98; 33 since Phase 104
assert len(set(ids)) == 33, "duplicate palette ids"
for pid in ("milk-plum", "night-kiwi", "black-gold",
            "peach-bloom", "champagne-slate", "cocoa-cloud",
            "meadow-violet", "winter-cherry"):
    assert pid in ids, pid
for name in ("Milk & Plum", "Night & Kiwi", "Black & Gold",
             "Peach Bloom", "Champagne & Slate", "Cocoa & Cloud",
             "Meadow & Violet", "Winter & Cherry"):
    assert name in APP, name
for hexv in ("#381932", "#FFF3E6", "#222222", "#89E900",
             "#050505", "#C9B27A", "#FFB4A2", "#E5989B",
             "#FDE2D2", "#FFF8F0", "#5C4034", "#5A5D64",
             "#E7D28F", "#53332A", "#B8CDE3", "#5E397F",
             "#9FB354", "#C10015", "#93B4D7"):
    assert hexv in APP, hexv
assert "app.js?v=110" in HTML and "games.js?v=110" in HTML
print("PHASE 93 OK")
