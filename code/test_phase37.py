"""Phase-37 tests: the Games lamp (owner: the Games section
opens in darkness with only a lamp and a hanging rope visible —
pull the rope, the light turns on, then the games appear).
Pure client feature: this suite pins the markup, the pull
interaction wiring, and the lit-state styles."""
HTML = open("webapp/index.html").read()
GAMES = open("webapp/games.js").read()
CSS = open("webapp/style.css").read()

for marker in ('id="games-dark"', 'id="pull-rope"', 'id="pull-knob"',
               'class="lamp-bulb"', 'class="lamp-shade"',
               "Pull the rope to turn on the light"):
    assert marker in HTML, marker
print("lamp markup OK")

for marker in ("nx_games_lit", "lightOn", "pointerdown",
               "pointermove", 'classList.add("lit")',
               'grid.style.visibility = "hidden"'):
    assert marker in GAMES, marker
print("pull interaction OK")

for marker in ("#games-dark", ".lamp-glow", ".lamp-bulb",
               ".pull-knob", "#games-dark.lit .lamp-bulb"):
    assert marker in CSS, marker
print("lamp styles OK")

print("PHASE-37 TESTS PASSED")
