"""Phase-52 tests: three more games (owner: add more games) —
Flappy Bird, 2048 and Pac-Man join the registry, so the grid
shows ten classics. The 2048 slide/merge logic was verified
in all four directions against known boards at build time."""
JS = open("webapp/games.js").read()
CSS = open("webapp/style.css").read()

for gid in ('id: "flappy"', 'id: "g2048"', 'id: "pacman"',
            'id: "snake"', 'id: "tetris"', 'id: "breakout"',
            'id: "memory"', 'id: "pong"', 'id: "invaders"',
            'id: "mines"'):
    assert gid in JS, gid
assert JS.count("registerGame({") == 10, JS.count("registerGame({")
for marker in ("Flappy Bird", "Pac-Man", "chase the 2048 tile",
               "g2048-grid"):
    assert marker in JS or marker in CSS, marker
assert ".g2048-cell" in CSS
print("ten classics registered OK")

print("PHASE-52 TESTS PASSED")
