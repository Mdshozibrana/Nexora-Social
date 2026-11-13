"""Phase-85 tests: the Post Design button style (owner picked
sample A — Gradient Glow — after two sample rounds).

The button previously had no CSS rule of its own at all; it
rendered as a plain browser button. It is now a sky-gradient
pill with white bold text, a sparkle and a soft sky glow,
sitting at the right of the upload row. (Phase 105 moved the
site accent from pink to sky; the Gradient Glow shape is unchanged.)
"""
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()

rule = CSS.split("#design-post {")[1].split("}")[0]
assert "linear-gradient(90deg, #8ED4F7, #3E8FD0)" in rule
assert "border-radius: 999px" in rule
assert "color: #fff" in rule and "font-weight: 700" in rule
assert "rgba(62, 143, 208, .45)" in rule
assert "margin-left: auto" in rule
assert '#design-post::before { content: "✦ "; }' in CSS
assert "#design-post:active { transform: scale(.96); }" in CSS
assert 'id="design-post"' in HTML
assert "app.js?v=118" in HTML and "style.css?v=118" in HTML
print("PHASE 85 OK")
