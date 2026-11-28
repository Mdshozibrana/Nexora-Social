"""Phase-75 tests: Nexa is text-only (owner: "Nexa এর ভয়েস
মেসেজের দরকার নেই" — her voice messages are not needed).

This supersedes the Phase 70/71 voice work at the owner's
word: the client no longer speaks, has no voice toggle, no
tap-to-hear bubbles and no audio unlock machinery; asking her
something is a single text chat call, after which she returns
to her day. Phase 183 removed the server endpoints entirely —
nothing in the client calls speak/reply any more, and the
routes answer 404.
"""
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()
MAIN = open("app/main.py").read()

# --- no voice machinery remains in the client -------------------
for gone in ("nexaSpeak", "nexaPlayAudio", "nexaDeviceSpeak",
             "nexaUnlockAudio", "NEXA_SILENT_WAV", "nexaPlayer",
             "nexaVoiceOn", "speechSynthesis", "nexa-hear",
             "nx_nexa_voice", '"/assistant/speak"',
             '"/assistant/reply"', "nexaTalking"):
    assert gone not in JS, gone
assert 'id="nexa-voice"' not in HTML
print("voice surface gone")

# --- the text path is intact ------------------------------------
assert '"/assistant/chat"' in JS
assert "sendNexa" in JS and "nexaBubble(reply" in JS
# she still returns to her day after answering
assert "nexaPairShown = true;" in JS
assert "nexaLifeTick" in JS
# the greeting no longer tries to speak
seg = JS[JS.index("function openAssistant()"):JS.index("function nexaStop()")]
assert "nexaSpeak" not in seg and "nexaBubble(hello" in seg
print("text path OK")

# --- server voice routes are GONE (Phase 183, audit M15) ---------
# The Phase 75 compromise ("endpoints stay, dormant") is over:
# the owner TEXT-ONLY order now removes the routes entirely.
assert '"/assistant/speak"' not in MAIN
assert '"/assistant/reply"' not in MAIN
assert "_gemini_tts" not in MAIN
assert "assistant_speak" not in MAIN
# and her self-description matches the text-only reality
assert "members chat with you by text" in MAIN
# the stale "spoken aloud" comment is gone from the client
assert "spoken aloud" not in JS
print("server voice routes gone OK")

assert "app.js?v=208" in HTML and "style.css?v=208" in HTML
print("PHASE 75 OK")
