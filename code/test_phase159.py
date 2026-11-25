"""Phase-159 REMOVAL guards (Phase 161, owner reversal, Nov 20 2026).

Owner (Phase 159): "এই গেমে এখানে রিমোট কন্ট্রোল দাও।"
Owner (Phase 161): "আর গেম থেকে রিমোট কন্ট্রোল তুলে ফেলো তখন
যেটা এড করছো।" — the joystick + SHOOT remote is gone, completely.
Same pattern as the Phase 152 Museum removal (test_phase86/87
became removal guards).

Covers: no remote element/class/listener/CSS/marker anywhere in
the served code; the board is back to its pre-159 structure
(stage.appendChild(cv), no wrapper); drag-to-aim is the ONLY input
and works exactly as before Phase 159 (same aim state, same
clamp, same release); the mascot is NOT hidden while Archery is
open; the help text is back to its pre-159 wording; Solo + 2
Players intact; neighbours (incl. Phase 160 .vname); backup 44
tables; routes 163; ?v=183 x10, no old version literals.
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

# 1. JS parses (node) — the removal touched the Archery closure, so
# a syntax slip would kill all 11 games, not just Archery.
for f in ("webapp/games.js", "webapp/app.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True)
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (games.js + app.js parse)")

# 2. Removal guards: NO remote element, class, listener, helper or
# marker anywhere in the served code.
DEAD = ("arch-board", "arch-remote", "arch-joy", "arch-knob",
        "arch-col", "arch-shoot", "arch-pwr", "arch-pwr-fill",
        "arch-pwr-lab", "remoteReset", "remoteMeter", "joySet",
        "JOY_R", "joyId", "mw.hidden", "Archery remote control",
        "board.appendChild(remote)", "board.appendChild(cv)")
for bit in DEAD:
    assert bit not in GAMES, ("games.js still has", bit)
    assert bit not in CSS, ("style.css still has", bit)
    assert bit not in HTML, ("index.html still has", bit)
assert "Phase 159" not in GAMES, "Phase 159 marker still in games.js"
assert "Phase 159" not in CSS, "Phase 159 marker still in style.css"
assert "Phase 159" not in HTML, "Phase 159 marker still in index.html"
assert GAMES.count("registerGame({") == 11, "games count changed"
print("removal OK (no remote markup/classes/helpers/markers anywhere)")

# 3. Board structure restored to pre-159: the canvas goes straight
# onto the stage — no wrapper, no remote sibling.
assert "    stage.appendChild(cv);" in ARCH, "canvas must mount directly"
assert ARCH.count("stage.appendChild(cv);") == 1
print("board structure OK (canvas mounts directly, no wrapper)")

# 4. Drag-to-aim is the ONLY input and is byte-for-byte the pre-159
# path: same aim state, same clamp (exactly ONCE now — the joystick
# duplicate is gone), same power range, same single release().
for bit in ('cv.addEventListener("pointerdown"',
            'cv.addEventListener("pointermove"',
            'cv.addEventListener("pointerup", release)',
            'cv.addEventListener("pointercancel", () => { aim = null; });',
            "const setAim =",
            "aim = { ang, sp };",
            "const release = () => {",
            "aim = null; state = \"fly\";"):
    assert bit in ARCH, bit
assert ARCH.count("Math.max(-1.35, Math.min(0.12, ang))") == 1, \
    "angle clamp must appear exactly once (setAim only)"
assert "Math.max(11, Math.min(27," in ARCH, "drag power 11..27"
assert ARCH.count("const release = () => {") == 1, "one release path"
assert "release();" not in ARCH.split(
    'cv.addEventListener("pointerup", release)')[0].split(
    "const release = () => {")[1], "no other release() callers"
# the board's own panel taps still start/advance the game
for branch in (
        'if (state === "intro") { state = "aim"; resumed = false; return; }',
        'if (state === "clear") { startLevel(level + 1, true); return; }',
        'if (state === "fail") { startLevel(level, true); return; }'):
    assert branch in ARCH, branch
print("drag-to-aim OK (only input; same aim, clamp, release as pre-159)")

# 5. Help text is back to the pre-159 wording — no remote, no SHOOT.
m = re.search(r'help: "(.*?)",', ARCH)
assert m, "archery help missing"
assert m.group(1) == (
    "Drag to aim — the dotted line previews your shot. "
    "Release to loose. Solo is a level climb: score the quota in "
    "10 arrows to advance. Bars speed up, multiply, the target "
    "shrinks, starts moving, and wind joins in. 2 Players: 6 "
    "arrows each on one phone. Invite: a challenge message to a "
    "friend."), m.group(1)
print("help OK (pre-159 wording, no remote/SHOOT)")

# 6. Mascot: Archery no longer touches it at all — it stays visible
# while the game is open, as before Phase 159.
assert 'getElementById("mascot-wrap")' not in ARCH
assert "mw" not in ARCH, "no mascot-hide variable may remain in Archery"
assert "return () => { dead = true; cancelAnimationFrame(raf); };" in ARCH
print("mascot OK (Archery never hides it; cleanup is plain)")

# 7. Game intact: Solo + 2 Players, dotted preview, level flow.
for bit in ("👤 Solo", "👥 2 Players", "if (aim && state === \"aim\")",
            "function startLevel(", "levelCfg("):
    assert bit in ARCH, bit
print("game intact OK (Solo/2P, preview, level flow)")

# 8. Neighbours intact (incl. Phase 160 .vname rule).
for bit in ("loadBloodDonors", "openNearby", "loadSkills", "sendNexa",
            "mascotOnView", "composer-post", "glassbar",
            "MASCOT_TIPS_BY_VIEW", "fitVerifiedNames", "vname"):
    assert bit in JS or bit in GAMES or bit in CSS, bit
print("neighbours OK (incl. Phase 160 .vname)")

# 9. No new endpoints, no schema change: routes still 163,
# backup still 44 tables.
with TestClient(app) as c:
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
    print("backup: 44 tables OK")
paths = {rt.path for rt in app.routes}
assert len(paths) == 181, len(paths)
print("routes: 163 OK (no new endpoints)")

# 10. Version.
assert HTML.count("?v=183") == 10, HTML.count("?v=183")
assert "?v=16" + "0" not in HTML
assert "app.js?v=183" in HTML and "games.js?v=183" in HTML
assert 'menu_url.rstrip("/") + "/?v=183"' in BOT
assert "Phase 161" in HTML
print("version OK (?v=183 x10, no old-version literals)")
print("PHASE 159 REMOVAL OK")
