"""Phase-89 tests: Archery becomes a level climb
(owner: make it prettier, add LEVELS that get harder step
by step, and design it so the player can SEE each new
level).

Solo now runs levels: every level opens with a big LEVEL
card over the game's themed sky, names what is new, and
sets a quota — score it in 10 arrows to advance, or retry
the level. The difficulty table (levelCfg) speeds the bars
up, adds bars, shrinks the target, starts it moving at
level 4 and adds wind at level 6. Six skies rotate so a
new level looks new. 2 Players and the DM invite stay as
they were; the invite now carries your best level too.
The state machine (intro -> aim -> clear/fail -> retry),
quota advancement and 2P were verified headlessly in node
before shipping, and a bullseye is still reachable.
"""
HTML = open("webapp/index.html").read()
GAMES = open("webapp/games.js").read()
MAIN = open("app/main.py").read()

# the level table: quota, bar growth, shrinking target,
# moving target from 4, wind from 6
for bit in ("levelCfg", "50 + (n - 1) * 20", "Math.min(240",
            "46 - (n - 1) * 2", "Math.max(30",
            "moveAmp: n >= 4", "wind: n >= 6", "NEW_AT"):
    assert bit in GAMES, bit
# six themed skies — a new level must LOOK new
for name in ("Night Range", "Dawn Ridge", "Ember Dusk",
             "Meadow Dark", "Storm Field", "Moonlight"):
    assert name in GAMES, name
# the screens a player meets: intro card, cleared, retry,
# best-level memory and the quota in the score line
for bit in ('"LEVEL " + level', "CLEARED!", "tap to retry Level",
            "Best level reached", "nx_archery_level",
            '"🏹 Level " + level', "cfg.quota"):
    assert bit in GAMES, bit
# the invite now brags about your level as well
assert 'I reached Level " + bestLevel' in GAMES
# solo progress bar + confetti bursts exist
for bit in ("scores[0] >= cfg.quota", "burst(TGT.x, TGT.y"):
    assert bit in GAMES, bit
# Nexa learned the climb
assert "level climb" in MAIN
assert "app.js?v=110" in HTML and "games.js?v=110" in HTML
print("PHASE 89 OK")
