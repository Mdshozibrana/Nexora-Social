"""Phase-47 tests: three more old-time games (owner) — Pong
(1972), Space Invaders (1978) and Minesweeper join Snake,
Tetris, Breakout and Memory Match in the registry, so the
games grid (built from the registry) shows seven classics."""
JS = open("webapp/games.js").read()
CSS = open("webapp/style.css").read()

for gid in ('id: "pong"', 'id: "invaders"', 'id: "mines"',
            'id: "snake"', 'id: "tetris"', 'id: "breakout"',
            'id: "memory"'):
    assert gid in JS, gid
for marker in ("Space Invaders", "Minesweeper", "first to 7",
               "mine-grid"):
    assert marker in JS or marker in CSS, marker
assert ".mine-cell" in CSS and ".mine-open" in CSS
print("seven classics registered OK")

print("PHASE-47 TESTS PASSED")
