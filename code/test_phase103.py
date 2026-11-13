"""Phase 103: After Rain THEMES removed (owner, Nov 8: "এটা
বাদ দাও").

The owner dropped the Phase 102 rain themes the same evening
they shipped. This revert restores the Phase 101 shape
exactly: one rain look (the classic droplets), one toggle
button, the stored per-account value back to "1"/"0". The
RAIN_THEMES table, the theme chips and setRainTheme are gone
from the client, the chips CSS is gone, and Nexa's manual no
longer mentions themes. The After Rain Effect itself — the
feature the owner originally asked for in Phase 101 — stays.
"""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase103.db"
os.environ["ADMIN_IDS"] = "777"

JS = open("webapp/app.js", encoding="utf-8").read()
CSS = open("webapp/style.css", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()
MAIN = open("app/main.py", encoding="utf-8").read()

# --- the themes are gone --------------------------------------------------
for gone in ("RAIN_THEMES", "setRainTheme", "rainTheme()",
             "rain-chip", "rainCfg"):
    assert gone not in JS, gone
assert ".rain-chips" not in CSS and ".rain-chip" not in CSS
assert "five themes" not in MAIN
print("themes removed OK")

# --- the Phase 101 effect survives intact ---------------------------------
assert "function rainCard()" in JS
assert "🌧️ After Rain Effect" in JS
assert 'localStorage.getItem(rainKey()) === "1"' in JS
assert 'localStorage.setItem(rainKey(), rainEnabled() ? "0" : "1")' in JS
assert "function syncRainFx()" in JS
assert "#rain-fx" in CSS
print("phase 101 rain intact OK")

# --- asset version ----------------------------------------------------------
assert "app.js?v=114" in HTML and "style.css?v=114" in HTML
print("asset version OK")

print("PHASE 103 OK")
