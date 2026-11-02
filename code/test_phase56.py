"""Phase-56 regression test: the post ⋮ options button
looked dead (owner report). Root cause: #reel-sheet-wrap
lived INSIDE <section id="view-videos">, and every other
view hides that section (display:none), so the fixed sheet
could never appear on the Feed. The wrap now sits at body
level, outside every view section."""
HTML = open("webapp/index.html").read()

assert HTML.count('id="reel-sheet-wrap"') == 1
videos_open = HTML.index('id="view-videos"')
videos_close = HTML.index("</section>", videos_open)
sheet = HTML.index('id="reel-sheet-wrap"')
assert not (videos_open < sheet < videos_close), \
    "the sheet is inside the videos section again"
first_section_end = HTML.index("</section>")
assert sheet > first_section_end
print("sheet placement OK")
