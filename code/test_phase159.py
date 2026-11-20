"""Phase-159 tests: Archery remote control (owner, Nov 20 2026).

Owner: "এই গেমে এখানে রিমোট কন্ট্রোল দাও। স্কিনে হাত দিলে
গেমস খেলা অসুবিধা হয়।" — a joystick + SHOOT remote anchored in
the bottom-right corner of the Archery board (the circled spot),
because dragging on the board to aim is awkward on his phone.

Covers: remote markup (board wrapper, joystick, knob, SHOOT,
power meter); the SAME aim state and the SAME release() as the
board drag (no parallel physics copy); dotted preview shows while
remote-aiming; drag-to-aim untouched; SHOOT also starts the level
and advances past intro/clear/fail/over, so the whole game is
playable from the remote alone; 360px geometry (remote clears the
quota bar, target, archer, mode buttons and bottom nav; mascot
hidden while Archery is open); help mentions the remote;
neighbours; backup 44 tables; routes 163; ?v=159 x10, no old
version literals.
"""
import hashlib, hmac, json, os, re, subprocess, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase159.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


ALICE = H(111, "Alice")

HTML = open("webapp/index.html").read()
GAMES = open("webapp/games.js").read()
CSS = open("webapp/style.css").read()
JS = open("webapp/app.js").read()
BOT = open("app/bot.py").read()

ARCH = GAMES[GAMES.index('id: "archery"'):GAMES.index("// Built last")]


def css_rule(sel):
    m = re.search(re.escape(sel) + r" \{([^}]*)\}", CSS, re.S)
    assert m, sel + " rule missing"
    return m.group(1)


def css_px(rule, prop):
    m = re.search(prop + r":\s*([\d.]+)px", rule)
    assert m, prop + " missing in " + rule[:60]
    return float(m.group(1))


# 1. JS parses (node) — the remote closes over game state, so a
# syntax slip would kill all 11 games, not just Archery.
for f in ("webapp/games.js", "webapp/app.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True)
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (games.js + app.js parse)")

# 2. Remote markup: board wrapper + joystick + knob + SHOOT + meter.
for bit in ("arch-board", "arch-remote", "arch-joy", "arch-knob",
            "arch-shoot", "arch-pwr", "arch-pwr-fill",
            "board.appendChild(remote)",
            "board.appendChild(cv)",
            "remote.setAttribute(\"aria-label\", \"Archery remote control\")"):
    assert bit in ARCH, bit
assert GAMES.count("registerGame({") == 11, "games count changed"
print("remote markup OK (board + joystick + SHOOT + power meter)")

# 3. SAME aim state, no parallel physics: the joystick writes the
# exact variable the drag writes, with the exact clamp and range.
assert "aim = { ang, sp: 11 + mag * 16 };" in ARCH, "joystick aim"
assert "aim = { ang, sp };" in ARCH, "drag aim (setAim)"
assert ARCH.count("Math.max(-1.35, Math.min(0.12, ang))") == 2, \
    "angle clamp must appear in setAim AND joySet"
assert "Math.max(11, Math.min(27," in ARCH, "drag power 11..27"
assert 11 + 16 == 27, "joystick full throw must equal drag max power"
# joystick only aims while the game is in the aim state
assert "if (state !== \"aim\") return;" in ARCH
assert "if (joyId !== e.pointerId || state !== \"aim\") return;" in ARCH
# lifting the stick does NOT fire: joyEnd only drops the pointer id
joy_end = ARCH[ARCH.index("const joyEnd"):ARCH.index(
    "pad.addEventListener(\"pointerup\", joyEnd);")]
assert "aim = null" not in joy_end, "lifting the stick must keep the aim"
assert "release()" not in joy_end, "lifting the stick must not shoot"
print("shared aim OK (joystick + drag write the same aim, same clamp)")

# 4. SAME release: SHOOT calls release(), the board pointerup calls
# release() — one flight path for both inputs.
assert "shoot.addEventListener(\"click\"" in ARCH
shoot_h = ARCH[ARCH.index("shoot.addEventListener(\"click\""):]
assert "release();" in shoot_h, "SHOOT must call release()"
assert 'cv.addEventListener("pointerup", release)' in ARCH
assert ARCH.count("const release = () => {") == 1, "one release path"
print("shared release OK (SHOOT + board pointerup -> release())")

# 5. Dotted preview: drawn exactly when aim is set in the aim
# state — the remote sets aim, so the preview shows for it too.
assert "if (aim && state === \"aim\")" in ARCH, "preview condition"
# drag input untouched
for bit in ('cv.addEventListener("pointerdown"',
            'cv.addEventListener("pointermove"',
            "const setAim ="):
    assert bit in ARCH, bit
print("preview + drag OK (preview condition unchanged, drag intact)")

# 6. Whole game from the remote alone: SHOOT starts the level and
# advances past every panel; modes untouched.
for branch in (
        'if (state === "intro") { state = "aim"; resumed = false; return; }',
        'if (state === "clear") { startLevel(level + 1, true); return; }',
        'if (state === "fail") { startLevel(level, true); return; }',
        'if (state === "over") { reset(); return; }'):
    assert branch in ARCH, branch
for bit in ("👤 Solo", "👥 2 Players"):
    assert bit in ARCH, bit
print("remote-only play OK (SHOOT starts + advances; Solo/2P intact)")

# 7. Help text mentions the remote.
m = re.search(r'help: "(.*?)",', ARCH)
assert m, "archery help missing"
assert "remote" in m.group(1).lower(), m.group(1)
assert "SHOOT" in m.group(1), m.group(1)
print("help OK (mentions the remote + SHOOT)")

# 8. CSS geometry at 360px: body padding is 0 12px, so the board is
# min(340, 336) wide and 336*460/340 tall; the remote must clear
# the quota bar, the target, the archer and the mode buttons.
remote_rule = css_rule(".arch-remote")
assert "position: absolute" in remote_rule, remote_rule
r_right = css_px(remote_rule, "right")
r_bottom = css_px(remote_rule, "bottom")
assert r_right == 6 and r_bottom == 38, (r_right, r_bottom)
board_rule = css_rule(".arch-board")
assert "position: relative" in board_rule, board_rule
joy_rule = css_rule(".arch-joy")
assert css_px(joy_rule, "width") == 84 and css_px(joy_rule, "height") == 84
shoot_rule = css_rule(".arch-shoot")
assert css_px(shoot_rule, "width") >= 44 and css_px(shoot_rule, "height") >= 44, \
    "SHOOT must be a thumb target (>=44px)"
board_w = min(340, 360 - 24)
board_h = board_w * 460 / 340
remote_w = 84 + 8 + 56 + 2 * 8   # joy + gap + shoot + padding
remote_h = max(84, 56 + 6 + 7 + 6 + 11) + 2 * 7
remote_left = board_w - r_right - remote_w
remote_top = board_h - r_bottom - remote_h
remote_bottom = board_h - r_bottom
archer_right = 90 * board_w / 340      # stickman + bow, canvas x<=90
bars_bottom = 289 * board_h / 460       # lowest bar row + height
quota_top = 434 * board_h / 460         # green progress bar top
target_bottom = (96 + 46) * board_h / 460
assert remote_left > archer_right, (remote_left, archer_right)
assert remote_top > bars_bottom, (remote_top, bars_bottom)
assert remote_top > target_bottom, (remote_top, target_bottom)
assert quota_top - remote_bottom >= 10, (quota_top, remote_bottom)
print("360px geometry OK (board %.0fx%.0f, remote %.0fx%.0f at "
      "left %.0f top %.0f; clears bar by %.1fpx)" % (
          board_w, board_h, remote_w, remote_h, remote_left,
          remote_top, quota_top - remote_bottom))

# 9. Mascot: it floats in this same corner, so Archery hides it on
# open and the cleanup restores it on exit.
assert 'getElementById("mascot-wrap")' in ARCH
assert "mw.hidden = true" in ARCH, "mascot must hide while Archery is open"
assert "mw.hidden = false" in ARCH, "cleanup must restore the mascot"
print("mascot OK (hidden while Archery is open, restored on exit)")

# 10. Neighbours intact.
for bit in ("loadBloodDonors", "openNearby", "loadSkills", "sendNexa",
            "mascotOnView", "composer-post", "glassbar",
            "MASCOT_TIPS_BY_VIEW"):
    assert bit in JS or bit in GAMES or bit in CSS, bit
print("neighbours OK")

# 11. No new endpoints, no schema change: routes still 163,
# backup still 44 tables.
with TestClient(app) as c:
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 44, len(r.json()["tables"])
    print("backup: 44 tables OK")
paths = {rt.path for rt in app.routes}
assert len(paths) == 163, len(paths)
print("routes: 163 OK (no new endpoints)")

# 12. Version.
assert HTML.count("?v=159") == 10, HTML.count("?v=159")
assert "?v=15" + "8" not in HTML
assert "app.js?v=159" in HTML and "games.js?v=159" in HTML
assert 'menu_url.rstrip("/") + "/?v=159"' in BOT
assert "Phase 159" in CSS and "Phase 159" in GAMES and "Phase 159" in HTML
print("version OK (?v=159 x10, no old-version literals)")
print("PHASE 159 OK")
