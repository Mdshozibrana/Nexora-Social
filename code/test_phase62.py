"""Phase-62 tests: the glassy sidebar opens on the FIRST tap and
opens faster (owner: "Sidebar স্লো কাজ করে। মাঝে মাঝে ১ ক্লিকে
ওপেন হয়না").

Root causes fixed:
1. Only the 26px chevron (#gb-toggle) carried the toggle handler,
   so taps on the pill's logo/body did nothing. Now a tap (pointerup
   with no drag) anywhere on the collapsed pill toggles it open via
   gbEndDrag; taps landing on rail items (.gb-item / #gb-foot) keep
   their own click actions.
2. The drag threshold was 7px — a normal finger tap drifts more
   than that, became a "drag", and gbSuppressClick ate the click.
   The threshold is now 12px, and a real tap toggles on pointerup
   with the trailing click suppressed so nothing double-fires.
3. Opening animated width + top + max-height + border-radius over
   .45s on a backdrop-filter panel (a full re-blur every frame).
   Only width + radius animate now, over .3s.
"""
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

# tap-to-open on the whole collapsed pill
assert "onItem" in JS
assert 'closest(".gb-item, #gb-foot")' in JS
end_at = JS.index("function gbEndDrag")
tap_block = JS[end_at:end_at + 1600]
assert 'e.type === "pointerup"' in tap_block
assert "toggleSidebar()" in tap_block
assert "gbSuppressClick = true" in tap_block
print("tap-to-open OK")

# wobbly taps are no longer eaten as drags
assert "Math.hypot(dx, dy) < 12" in JS
assert "Math.hypot(dx, dy) < 7" not in JS
print("drag threshold OK")

# the chevron keeps its own handler (keyboard + fallback path)
assert '$("gb-toggle").onclick = toggleSidebar' in JS
# drag machinery from Phase 48 is intact
for marker in ("nx_gb_pos", "gbRestorePos", "gbApplyPos",
               "gbSuppressClick"):
    assert marker in JS, marker
print("existing controls OK")

# faster, cheaper open animation
assert "width .3s cubic-bezier(.32, .72, .24, 1)" in CSS
assert "top .45s" not in CSS
assert "max-height .45s" not in CSS
assert "#glassbar:not(.open) { touch-action: none" in CSS
print("open animation OK")

print("PHASE 62 OK")
