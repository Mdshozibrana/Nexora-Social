"""Phase-43 tests: the Admin Dashboard redesign (owner: make it
unique & attractive). Pins the gradient hero with its live
headline numbers, the colourful stat tiles, pill section
headers, glowing bars, and the JS that fills the hero."""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

for marker in ('class="admin-hero"', 'id="ah-members"',
               'id="ah-active"', 'id="ah-posts"', 'id="ah-reports"',
               'class="admin-live"', 'class="live-dot"',
               "Owner control room", "?v=63"):
    assert marker in HTML, marker
# the dashboard's data containers survived the redesign
for marker in ('id="dash-tiles"', 'id="admin-stats"',
               'id="dash-signups"', 'id="admin-reports"'):
    assert marker in HTML, marker
print("hero markup OK")

for marker in (".admin-hero", "livePulse", ".ah-num",
               ".admin-stats .stat-card:nth-child(6n+1)",
               "#view-admin .admin-sec"):
    assert marker in CSS, marker
print("hero styles OK")

for marker in ('$("ah-members")', '$("ah-active")',
               '$("ah-posts")', '$("ah-reports")'):
    assert marker in JS, marker
print("hero wiring OK")

print("PHASE-43 TESTS PASSED")
