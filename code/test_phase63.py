"""Phase-63 tests: pressing Enter in the search bar searches
(owner: "সার্চ বারে লিখে কিবোর্ড ইনটার দিলে সার্চ হয়না").

Root cause: runSearch was wired ONLY to the Search button's
click. The input is not inside a <form> and had no keyboard
handler, so Enter did nothing. The fix adds a keydown listener:
Enter -> preventDefault + runSearch(trimmed value) + blur (the
mobile keyboard closes so the results are visible). The button
path and hashtag-chip path (searchTag) are unchanged.
"""
JS = open("webapp/app.js").read()

at = JS.index('$("search-input").addEventListener("keydown"')
block = JS[at:at + 420]
assert 'e.key === "Enter"' in block
assert "e.preventDefault()" in block
assert 'runSearch($("search-input").value.trim())' in block
assert '$("search-input").blur()' in block
print("enter-to-search OK")

# the older triggers still exist
assert '$("search-go").onclick' in JS
assert "function searchTag" in JS and "async function runSearch" in JS
print("existing triggers OK")

print("PHASE 63 OK")
