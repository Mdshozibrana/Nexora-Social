"""Phase-39 tests: the Glassy Sidebar (owner's reference video —
a slim frosted-glass icon rail at the left edge that expands with
animation into a wide labelled glass panel). It REPLACES the old
drawer: this suite pins the new markup, the expansion wiring,
the glass styles, the badge hooks, and that no drawer markup or
logic survives."""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

for marker in ('id="glassbar"', 'id="gb-backdrop"', 'id="gb-toggle"',
               'class="gb-logo"', "CONNECT ANYWHERE",
               'data-go="designs"', 'data-go="messages"',
               'data-go="notifications"', 'id="gb-msg-badge"',
               'id="gb-bell-badge"', 'id="gb-admin"',
               'id="gb-official"', 'id="gb-logout"',
               'id="gb-foot"', 'id="gb-foot-name"',
               'class="gb-online"', "?v=47"):
    assert marker in HTML, marker
assert 'id="drawer-wrap"' not in HTML
assert 'class="drawer-item"' not in HTML
print("sidebar markup OK")

for marker in ("openSidebar", "closeSidebar", "toggleSidebar",
               "syncSidebarActive", "paintGlassFoot",
               '$("gb-toggle").onclick', '$("gb-backdrop").onclick',
               '$("gb-admin")', '$("gb-official")',
               '$("gb-bell-badge")', '$("gb-msg-badge")'):
    assert marker in JS, marker
assert "openDrawer" not in JS and "closeDrawer" not in JS
assert "drawer-wrap" not in JS
print("sidebar wiring OK")

for marker in ("#glassbar {", "backdrop-filter: blur(18px)",
               "#glassbar.open", "width: min(302px, 84vw)",
               "cubic-bezier(.32, .72, .24, 1)",
               ".gb-item.active", ".gb-online",
               "#glassbar:not(.open) .gb-badge"):
    assert marker in CSS, marker
print("glass styles OK")

print("PHASE-39 TESTS PASSED")
