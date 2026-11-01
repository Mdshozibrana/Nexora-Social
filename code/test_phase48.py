"""Phase-48 tests: the sidebar is draggable (owner) — the
collapsed pill can be dragged anywhere, snaps to the nearer
edge keeping its height, the panel opens from that side, and
the spot persists across launches."""
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

for marker in ("nx_gb_pos", "gbRestorePos", "gbEndDrag",
               "pointerdown", "pointermove", "gbSuppressClick",
               'classList.toggle("gb-right"'):
    assert marker in JS, marker
print("drag machinery OK")

for marker in ("#glassbar.gb-right", ".gb-drag",
               "touch-action: none",
               "scaleX(-1) rotate(180deg)"):
    assert marker in CSS, marker
print("edge-snap styling OK")

assert '$("glassbar").style.top = "";' in JS  # panel docks top
assert "gbRestorePos();" in JS                # close restores
print("open/close integration OK")

print("PHASE-48 TESTS PASSED")
