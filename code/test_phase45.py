"""Phase-45 tests: one sidebar control only (owner: the sidebar
seemed to exist twice). The hero ☰ button — a second trigger for
the same sidebar — is removed from the markup and the wiring;
the glass pill's chevron remains the single way in."""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()

assert 'id="hero-menu"' not in HTML
assert "hero-menu" not in JS
assert 'id="glassbar"' in HTML and "?v=101" in HTML
for marker in ('$("gb-toggle").onclick = toggleSidebar',
               "function toggleSidebar", "function openSidebar"):
    assert marker in JS, marker
print("single sidebar control OK")

print("PHASE-45 TESTS PASSED")
