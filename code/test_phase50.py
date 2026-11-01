"""Phase-50 tests: the stretched profile photo fix (owner's
screenshot) — a generic ".post img { width: 100% }" rule was
catching the header avatar <img> and stretching the round
profile photo into a wide banner, pushing the author name
off-screen. The generic rule is gone (post media is styled
by .post-media), the avatar img pins its own size, and the
name column can shrink with an ellipsis instead of
overflowing."""
CSS = open("webapp/style.css").read()

assert ".post img, .post video" not in CSS
print("generic .post img rule removed OK")

assert "img.avatar { object-fit: cover; width: 42px; height: 42px;" in CSS
assert ".post-media img, .post-media video" in CSS  # media intact
print("avatar pinned, media styling intact OK")

assert "min-width: 0" in CSS and \
       ".post-name { font-weight: 700; font-size: 15px; overflow: hidden;" in CSS
print("name column shrink/ellipsis OK")

print("PHASE-50 TESTS PASSED")
