"""Phase-82 tests: leaderboard name opens the profile (owner:
"নামে বা ছবিতে ক্লিক করলে তার প্রোফাইলে নিয়ে যাবে").

The avatar was already a profile button; the name beside it did
nothing. Now both take you to that member's profile.
"""
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()

# the name is wired to the same profile opener as the avatar
assert 'nm.classList.add("rank-link");' in JS
assert "nm.onclick = () => openProfile(r.telegram_id);" in JS
assert "btn.onclick = () => openProfile(r.telegram_id);" in JS
# the tap affordance
assert ".rank-link { cursor: pointer; }" in CSS
assert "app.js?v=88" in HTML and "style.css?v=88" in HTML
print("PHASE 82 OK")
