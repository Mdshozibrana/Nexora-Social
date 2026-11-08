"""Phase 102: After Rain Effect THEMES (owner, Nov 8: "আরো এড
করো After rain effect theme").

The Phase 101 rain card gains five rain themes — Drizzle,
Classic, Monsoon, Golden, Night — picked with chips on the
card (the active theme is the pink pill, readable at a
glance). Each theme retunes the same engine: droplet count,
size, growth, slide chance, droplet colours and the mist
gradient. The stored per-account value is now the theme id
("0" = off); the Phase 101 value "1" still reads as Classic,
so an existing toggle survives the upgrade. Picking a chip
turns the rain on with that theme at once; the big toggle
button still turns it off / back on (Classic). Client-only,
like Phase 101; this suite pins the contract.
"""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase102.db"
os.environ["ADMIN_IDS"] = "777"

JS = open("webapp/app.js", encoding="utf-8").read()
CSS = open("webapp/style.css", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()
MAIN = open("app/main.py", encoding="utf-8").read()

# --- the five themes exist with engine parameters -----------------------
assert "const RAIN_THEMES = {" in JS
for tid in ("drizzle", "classic", "monsoon", "golden", "night"):
    assert tid + ": { label:" in JS, tid
for label in ("🌦️ Drizzle", "🌧️ Classic", "⛈️ Monsoon",
              "🌅 Golden", "🌙 Night"):
    assert label in JS, label
# each theme carries the knobs the engine reads
for knob in ("cap:", "div:", "spawn:", "size:", "grow:",
             "slide:", "alpha:", "stops:", "mist:"):
    assert knob in JS, knob
print("rain themes OK")

# --- stored value: theme id now, Phase 101 "1" still means Classic ------
assert "function rainTheme()" in JS
assert 'if (v === "1") return "classic";' in JS
assert "if (v && RAIN_THEMES[v]) return v;" in JS
assert "return rainTheme() !== null;" in JS
print("storage upgrade OK")

# --- chips on the card, active one highlighted, off chip included -------
assert "function rainCard()" in JS
assert 'ch.className = "rain-chip"' in JS
assert 'mkChip("off", "🚫 Off")' in JS
assert 'ch.dataset.theme === (rainTheme() || "off")' in JS
assert ".rain-chips" in CSS and ".rain-chip.active" in CSS
print("theme chips OK")

# --- picking a theme applies it immediately through the engine ----------
assert "function setRainTheme(id)" in JS
assert "c.style.background = rainCfg.mist;" in JS
assert "rainCfg = RAIN_THEMES[theme];" in JS
# the engine actually reads the theme knobs
for use in ("cfg.cap", "cfg.spawn", "cfg.slide", "cfg.stops",
            "cfg.alpha"):
    assert use in JS, use
print("theme engine wiring OK")

# --- the master toggle still works: off, or Classic back on -------------
assert 'setRainTheme(rainEnabled() ? null : "classic")' in JS
print("master toggle OK")

# --- Nexa's manual names the themes --------------------------------------
assert "five themes" in MAIN and "Drizzle, Classic, Monsoon" in MAIN
print("nexa manual OK")

# --- asset version --------------------------------------------------------
assert "app.js?v=102" in HTML and "style.css?v=102" in HTML
print("asset version OK")

print("PHASE 102 OK")
