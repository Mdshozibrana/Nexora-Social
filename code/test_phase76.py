"""Phase-76 tests: images heal themselves after a bad first
open (owner screenshot: the whole Design gallery — and by his
words the whole site — showed broken-image icons while the
data itself loaded, and the boot fallback line was visible).

Diagnosis, verified from here: the media code is unchanged
since it worked (git diff of the last five phases shows no
/media or mediaUrl change), the served app.js is byte-identical
to the repo, and the /media gate answers 401 correctly without
a token. The fallback line in his screenshot only appears when
the first loadMe/loadFeed attempt rejects — i.e. the app
opened against a cold, still-waking free server; the JSON
calls recovered on retry/navigation, but a WebView never
retries a failed <img>, so every image stayed broken.

Fix: (1) a capture-phase error listener retries any /media
IMG or VIDEO up to 3 times with backoff and a cache-buster;
(2) the boot chain retries once after 2s before showing the
"open in Telegram" fallback.
"""
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()

# --- image self-healing ----------------------------------------
for bit in ('document.addEventListener("error"',
            't.tagName !== "IMG" && t.tagName !== "VIDEO"',
            'src.includes("/media/")', "t.dataset.mr",
            "tries >= 3", '"&r="', "800 * (tries + 1)"):
    assert bit in JS, bit
print("image retry OK")

# --- boot retry --------------------------------------------------
assert "function bootFailed()" in JS
assert "loadMe().then(() => loadFeed(true)).catch(bootFailed)" in JS
assert JS.count("loadMe().then(() => loadFeed(true))") == 2
# the fallback text itself is unchanged for a genuine failure
assert "Please open this app from inside Telegram." in JS
print("boot retry OK")

assert "app.js?v=111" in HTML and "style.css?v=111" in HTML
print("PHASE 76 OK")
