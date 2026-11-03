"""Phase-73 tests: Nexa lives her own day, and the chat is
ephemeral (owner: she should always be doing something —
work, cooking, studying, cleaning, gym, running — and when a
second question is asked, the previous question + answer
disappear).

While she is not answering, the stage rotates her activity
scenes (life-*.webp, same character) with a status caption;
while she thinks or speaks, the rotation pauses (nexaBusy).
Each new question clears the visible log once a pair has been
shown — the server-side history (nexaHist) is untouched, so
she still remembers the conversation.
"""
import os

JS = open("webapp/app.js").read()
MAIN = open("app/main.py").read()

# --- her day: scenes exist and are wired ------------------------------
SCENES = ("life-work", "life-cooking", "life-study",
          "life-gym", "life-cleaning", "life-run",
          "life-garden", "life-painting", "life-guitar",
          "life-yoga")
for name in SCENES:
    assert os.path.exists(f"webapp/nexa/{name}.webp"), name
    assert name in JS, name
for label in ("is working", "is cooking", "is studying",
              "at the gym", "is cleaning", "out running",
              "watering her plants", "is painting",
              "playing guitar", "doing yoga"):
    assert label in JS, label
for bit in ("NEXA_LIFE", "nexaLifeTick", "nexaLifeStart()",
            "nexaLifeStop()", "setInterval(nexaLifeTick, 6000)"):
    assert bit in JS, bit
# rotation pauses while she answers
assert "if (nexaBusy) return;" in JS
assert "nexaBusy = true" in JS and "nexaBusy = false" in JS
# leaving the assistant view stops the rotation
assert "nexaLifeStop();\n  nexaBusy = false;" in JS
print("life OK")

# --- ephemeral chat -----------------------------------------------------
assert "nexaPairShown" in JS
assert 'if (nexaPairShown) $("nexa-log").innerHTML = "";' in JS
# context for the server is NOT cleared
assert 'nexaHist.push({ role: "user", text: text });' in JS
assert 'nexaHist.push({ role: "nexa", text: reply });' in JS
print("ephemeral OK")

HTML = open("webapp/index.html").read()
assert "app.js?v=83" in HTML and "style.css?v=83" in HTML
print("PHASE 73 OK")
