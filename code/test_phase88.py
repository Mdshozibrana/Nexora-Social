"""Phase-88 tests: Archery joins the Games page (owner, from
the screenshot he shared — one archer still aiming, the other
already shooting at SUCCESS).

Solo against a saved best, two players taking turns on one
phone, and an invite: a challenge sent to a followed friend
as a normal DM carrying your best score. (Real-time online
matches are not part of this phase.) The game's flight,
scoring-plane and turn logic were verified headlessly in
node before shipping: scoring shots exist at every bar
phase, bullseyes are reachable, solo spends exactly 10
arrows and 2P alternates to a finish.
"""
HTML = open("webapp/index.html").read()
GAMES = open("webapp/games.js").read()
CSS = open("webapp/style.css").read()
MAIN = open("app/main.py").read()

assert 'id: "archery"' in GAMES and "🏹 Archery" in GAMES
assert GAMES.count("registerGame({") == 11
# the scene from the screenshot, rebuilt as our own game
for bit in ("S U C C E S S", "levelCfg", "planeHit", "BULLSEYE",
            "nx_archery_best"):
    assert bit in GAMES, bit
# modes + invite over the normal DM route
for bit in ("👤 Solo", "👥 2 Players", "🏹 Invite friend",
            '"/me/following"', '"/messages/" + u.telegram_id',
            "I challenge you to Archery"):
    assert bit in GAMES, bit
for bit in (".arch-invite", ".arch-invite-row", ".arch-row"):
    assert bit in CSS, bit
# Nexa knows the eleventh game
assert "11 games" in MAIN and "Archery" in MAIN
assert "app.js?v=113" in HTML and "games.js?v=113" in HTML
print("PHASE 88 OK")
