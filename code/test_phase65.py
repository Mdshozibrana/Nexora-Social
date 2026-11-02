"""Phase-65 tests: leaderboard names stay on one line (owner's
screenshot: his own row wrapped — "MD Shozib Rana" on one line,
"(You)" + badge dropped to the next).

Root cause: .rank-name was a plain flex child with no min-width
and the row builder put first_name + " (You)" as one wrapping
text node. Fix: the name gets its own .rank-title span (nowrap +
ellipsis, the Phase 50 pattern), the verified badge is pinned
flex:none beside it, and "(You)" moves to the muted username
line. .rank-name becomes a wrapping flex row with min-width: 0
and the username line takes a full-width flex basis.
"""
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

# the old wrapping construction is gone
assert 'nm.textContent = r.first_name + (isMe ? " (You)" : "")' not in JS
# name in its own title span, badge after it
at = JS.index('title.className = "rank-title"')
block = JS[at - 200:at + 1400]
assert "title.textContent = r.first_name;" in block
assert "nm.appendChild(title)" in block
assert "verifiedBadge()" in block
# (You) now joins the username line
assert 'isMe ? "(You)" : ""' in block
assert 'r.username ? "@" + r.username : ""' in block
print("row builder OK")

# CSS: one-line title with ellipsis, pinned badge, full-width subline
assert ".rank-title" in CSS
title_rule = CSS[CSS.index(".rank-title"):CSS.index(".rank-title") + 200]
assert "white-space: nowrap" in title_rule
assert "text-overflow: ellipsis" in title_rule
name_rule = CSS[CSS.index(".rank-name {"):CSS.index(".rank-name {") + 200]
assert "min-width: 0" in name_rule
assert ".rank-name .verified { flex: none; }" in CSS
assert "flex: 0 0 100%" in CSS
print("row CSS OK")

print("PHASE 65 OK")
