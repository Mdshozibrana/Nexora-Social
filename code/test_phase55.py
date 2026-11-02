"""Phase-55 tests: camera badges + points card (owner: remove
the wide Change photo/cover buttons — put a camera icon ON
the profile photo and ON the cover; and decorate the My
Points section, it looked too plain)."""
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

assert 'cam.className = "cam-badge cover-cam"' in JS
assert 'cam.className = "cam-badge avatar-cam"' in JS
assert 'cam.title = "Change cover photo"' in JS
assert 'cam.title = "Change profile photo"' in JS
assert '$("cover-file").click()' in JS
assert '$("profile-file").click()' in JS
assert '"📷 Change profile photo"' not in JS
assert '"🖼️ Change cover photo"' not in JS
print("camera badges OK")

for marker in ("points-card", "points-head", "points-balance",
               "points-today", "ph-row", "REASON_META",
               "Daily check-in", "Referral bonus"):
    assert marker in JS or marker in CSS, marker
assert ".cam-badge" in CSS and ".avatar-wrap" in CSS
assert ".points-card" in CSS and ".ph-amt" in CSS
print("points card OK")

print("PHASE-55 TESTS PASSED")
