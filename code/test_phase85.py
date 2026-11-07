"""Phase-85 tests: the Post Design button style (owner picked
sample A — Gradient Glow — after two sample rounds).

The button previously had no CSS rule of its own at all; it
rendered as a plain browser button. It is now a pink-gradient
pill with white bold text, a sparkle and a soft pink glow,
sitting at the right of the upload row.
"""
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()

rule = CSS.split("#design-post {")[1].split("}")[0]
assert "linear-gradient(90deg, #FF8FBE, #E84393)" in rule
assert "border-radius: 999px" in rule
assert "color: #fff" in rule and "font-weight: 700" in rule
assert "rgba(232, 67, 147, .45)" in rule
assert "margin-left: auto" in rule
assert '#design-post::before { content: "✦ "; }' in CSS
assert "#design-post:active { transform: scale(.96); }" in CSS
assert 'id="design-post"' in HTML
assert "app.js?v=99" in HTML and "style.css?v=99" in HTML
print("PHASE 85 OK")
