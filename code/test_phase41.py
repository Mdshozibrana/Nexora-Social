"""Phase-41 tests: the sidebar coverage fix (owner, with a
screenshot: the collapsed glass rail ran nearly the full height
of the screen and covered the hero and headings). Collapsed, the
sidebar must shrink to a small pill — logo + chevron only — with
a single attention dot for unread messages/notifications; all
items live only in the expanded panel."""
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

assert 'id="gb-dot"' in HTML and "?v=103" in HTML
print("markup OK")

for marker in ("#glassbar:not(.open) .gb-item",
               "#glassbar:not(.open) .gb-sec",
               "#glassbar:not(.open) .gb-foot",
               "#gb-dot", "#glassbar.open #gb-dot"):
    assert marker in CSS, marker
print("collapsed pill styles OK")

for marker in ("paintGbDot", "gbBellCount", "gbMsgCount",
               '$("gb-dot")'):
    assert marker in JS, marker
print("attention dot wiring OK")

print("PHASE-41 TESTS PASSED")
