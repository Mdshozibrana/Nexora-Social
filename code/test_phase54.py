"""Phase-54 tests: post options (owner: feed posts from
others had no options — no Share, Save, Report like Facebook).
Every post card now ends its action row with a ⋮ Options
button opening the shared options sheet (Save, Share, Copy
link, Download, View profile, Follow/Unfollow, Not
interested, Report for others' posts; Delete for your own).
The old lone 🗑/⚑ card buttons are gone."""
JS = open("webapp/app.js").read()

assert JS.count("openReelMenu(p, el)") == 2  # reel rail + post card
assert 'menuBtn.title = "Options"' in JS
assert "Delete post" not in JS and "Report post" not in JS
print("post card menu wiring OK")

for marker in ('"Save"', '"Share"', '"Copy link"', '"Download"',
               '"View profile"', '"Not interested"', '"Report"',
               '"Delete"'):
    assert marker in JS, marker
assert '"/posts/" + p.id + "/save"' in JS
assert '"/reports"' in JS and '"/posts/" + p.id' in JS
print("sheet contents OK")

print("PHASE-54 TESTS PASSED")
