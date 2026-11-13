"""Phase-80 tests: Nearby wears the Story Circles design
(owner picked Sample F after two earlier sample rounds:
A/B/C, then D/E/F against G/H/I in the final round).

Contract: a stories row up top (gradient rings, photo or
initial, first name + distance, an Invite circle that shares
the bot link, and an "N online" chip), bubble avatar pins on
the map instead of plain blue dots, a pink person pin for
oneself, and person cards with an explicit Route button.
Behaviour from Phase 78 is untouched: opt-in, 500 m, fuzzing,
routes, 20 s refresh.
"""
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()

# --- markup -------------------------------------------------------
for bit in ('id="nearby-stories"', 'id="nearby-stories-head"',
            'id="nearby-count"', "Around you now"):
    assert bit in HTML, bit
print("markup OK")

# --- client behaviour ----------------------------------------------
for bit in ("function nbPaintStories(people)", "function nbBubbleIcon(q)",
            "function nbMeIcon()", "function nbAvaHTML(q, cls)",
            "mediaUrl(q.photo_file_id)", "nb-route-btn",
            '" online"', "t.me/share/url",
            "https://t.me/NexoraSocial_bot"):
    assert bit in JS, bit
# the stories + cards are painted from the same refresh as markers
seg = JS[JS.index("function nbPaintPeople(people)"):]
assert "nbPaintStories(people);" in seg
# toggling sharing off clears the stories too
assert '$("nearby-stories").innerHTML = "";' in JS
print("client OK")

# --- the look --------------------------------------------------------
for bit in (".nb-ring.r0", "conic-gradient(from 210deg",
            ".nb-pin::after", ".nb-me-pin::after", ".nb-online",
            ".nb-card", ".nb-route-btn", ".nb-stories"):
    assert bit in CSS, bit
# Leaflet's default divIcon white box must not frame the pins
assert ".nb-wrap { background: transparent !important;" in CSS
print("style OK")

assert "app.js?v=118" in HTML and "style.css?v=118" in HTML
print("PHASE 80 OK")
