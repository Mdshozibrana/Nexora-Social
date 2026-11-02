"""Phase-53 tests: the hero identity strip is removed
(owner's circled screenshot: the name + @handle + posts/
followers/following counts + points chip sat under the
wordmark on every user's screen and looked cluttered).
The hero keeps only the wordmark and the bell/message/
search buttons; the same facts still live on profiles and
in Tasks, and no code may reference the removed elements."""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

for gone in ("hero-row", "profile-line", 'id="stats"',
             "points-chip"):
    assert gone not in HTML, gone
    assert gone not in JS, gone
    assert gone not in CSS, gone
print("strip fully removed OK")

for kept in ('id="app-name"', 'id="hero-bell"', 'id="hero-msg"',
             'id="hero-search"', 'id="bell-badge"', 'id="msg-badge"'):
    assert kept in HTML, kept
assert '"⭐ My points: "' in JS      # points still shown in Tasks
assert "u.points" in JS             # and on profiles / admin detail
print("hero essentials + points homes kept OK")

print("PHASE-53 TESTS PASSED")
