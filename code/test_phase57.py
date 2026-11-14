"""Phase-57 tests: decorated monetization card (owner: give
the Monetization section a beautiful card) + the profile
stats line drops posts/points (owner circled them: no need
for posts and Points there)."""
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

for marker in ("mon-card fancy", "mon-hero", "mon-overall",
               "targets met", "mon-check", "MON_ICONS"):
    assert marker in JS, marker
for marker in (".mon-hero", ".mon-bar", ".mon-check", ".mc-count"):
    assert marker in CSS, marker
print("monetization card OK")

# Phase 120: the whole-file guard moved into the profile slice —
# the rule is about the profile stats line only; the admin
# Verify-by-Username card (admin-only) shows a member's post
# count too.
prof = JS[JS.index("async function openProfile"):
          JS.index("async function loadProfilePosts")]
assert 'u.posts + " posts' not in prof
assert '" points"' not in prof and "u.points" not in prof
assert prof.count('" followers · "') == 2  # initial + follow repaint
print("stats line OK")

print("PHASE-57 TESTS PASSED")
