"""Phase 101: After Rain Effect in Me (owner, Nov 8: "Bot এ Me
তে After Rain Effect এড করো").

A purely local, per-account decoration on the Me (profile)
screen: a rain-on-glass canvas — droplets rest, gather, grow,
and occasionally slide down leaving a fading trail, under a
soft post-rain mist. It is OFF by default, the choice is saved
per account under nx_rain_<telegram_id> (the Phase 96/97
pattern, so two accounts on one phone never share the toggle),
the canvas runs only while the profile view is on screen, it
never takes a tap (pointer-events: none), and
prefers-reduced-motion keeps it still. No server state is
involved; this suite pins the client contract.
"""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase101.db"
os.environ["ADMIN_IDS"] = "777"

JS = open("webapp/app.js", encoding="utf-8").read()
CSS = open("webapp/style.css", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()
MAIN = open("app/main.py", encoding="utf-8").read()

# --- the card exists and is mounted in myExtras, unconditionally -------
assert "function rainCard()" in JS
assert "🌧️ After Rain Effect" in JS
assert "wrap.appendChild(rainCard())" in JS
# it sits after Data Control in the extras stack
assert (JS.index("wrap.appendChild(dataCard())") <
        JS.index("wrap.appendChild(rainCard())"))
print("rain card mounted OK")

# --- per-account persistence, OFF by default ---------------------------
assert '"nx_rain_" +' in JS or '"nx_rain_"' in JS
assert "function rainKey()" in JS
assert "function rainEnabled()" in JS
assert 'localStorage.getItem(rainKey()) === "1"' in JS
print("per-account toggle OK")

# --- the effect engine + lifecycle -------------------------------------
for fn in ("function rainCanvas()", "function rainStep()",
           "function rainStart()", "function rainStop()",
           "function syncRainFx()"):
    assert fn in JS, fn
# runs only on the profile (Me) view, and only when enabled
assert 'currentView === "profile" && rainEnabled()' in JS
# showView drives it on every view change
assert "syncRainFx();\n  moveNavPill();" in JS or \
       JS.count("syncRainFx();") >= 2
# reduced motion keeps it still
assert "prefers-reduced-motion" in JS
# sliding drops leave a fading trail
assert "trail.push(" in JS
print("rain engine + lifecycle OK")

# --- the canvas can never block a tap and layers under the nav ---------
assert "#rain-fx" in CSS and "pointer-events: none" in CSS
assert "z-index: 60" in CSS
assert "#rain-fx[hidden]" in CSS
print("canvas layering OK")

# --- the toggle flips the saved value and re-syncs immediately ---------
assert 'localStorage.setItem(rainKey(), rainEnabled() ? "0" : "1")' in JS
print("toggle behaviour OK")

# --- Nexa's manual knows the card ---------------------------------------
assert "Rain Effect card" in MAIN
print("nexa manual OK")

# --- asset version -------------------------------------------------------
assert "app.js?v=103" in HTML and "style.css?v=103" in HTML
print("asset version OK")

print("PHASE 101 OK")
