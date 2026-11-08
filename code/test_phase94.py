"""Phase-94 tests: the Archery solo run RESUMES (owner,
from his screenshot at Level 1: "যে লেভেলে রেখে আসবো
সেখান থেকে পরে আসে না কেনো" — why doesn't it come back
at the level I left?).

Cause: nx_archery_level only ever stored the BEST level
for display/invite; the run itself hard-started at
level 1 with banked 0 on every open. Now the run is
saved as nx_archery_run {level, banked} at every level
entry (and at the NEXT level the moment one is cleared),
startSolo() restores it on open and on the Solo button,
the intro panel says "↩ Resumed — your saved run
continues here", a 🆕 New run button deliberately starts
over, and reset() no longer wipes a solo run. Verified
headlessly on the real games.js: a seeded {level 4,
banked 170} run reopens as "Level 4 · 0/110 · Total:
170", New run returns to Level 1 and stores {1,0}, and
the Solo button resumes {6,300}.
"""
HTML = open("webapp/index.html").read()
GAMES = open("webapp/games.js").read()
MAIN = open("app/main.py").read()

for bit in ("nx_archery_run", "loadRun", "saveRun",
            "startSolo", "let resumed",
            "Resumed — your saved run continues here",
            "🆕 New run", "saveRun(level + 1, banked)",
            "saveRun(level, banked)"):
    assert bit in GAMES, bit
# opening the game goes through the resuming entry point
assert "startSolo();\n    raf = requestAnimationFrame(step);" in GAMES
assert 'mkBtn("👤 Solo", startSolo);' in GAMES
# Nexa can explain the resume
assert "resumes where you left it" in MAIN
assert "app.js?v=101" in HTML and "games.js?v=101" in HTML
print("PHASE 94 OK")
