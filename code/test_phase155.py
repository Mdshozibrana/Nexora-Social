"""Phase-155 tests: Nexora mascot helper (owner pick #11 plush head,
recoloured to Organic Clay sky; owner order Nov 20, 2026, 07:20-08:11
Dhaka — mascot spotted in an Instagram reel, 12 designs in 4 batches,
#11 picked, head only, colour matched to Nexora Social).

A floating mascot button (vendored head image, shown as a circle) in
the bottom-right corner above the bottom nav; tap -> a speech bubble
with ONE rotating helpful tip. The bubble NEVER opens on its own.
Tips are all true about live features — numbers cross-checked against
config.py (DAILY_TASKS / MONETIZATION), not hardcoded in the test.
Nexa is untouched. Client-side only: no new endpoints, no schema
change, backup 43 tables, routes 158.
"""
import hashlib, hmac, json, os, re, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase155.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app, SessionLocal
from app import models
from app.config import DAILY_TASKS, MONETIZATION


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData",
                      os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


ALICE = H(111, "Alice")

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()

# Live numbers the tips must match (read from config, never hardcoded).
CHECKIN_PTS = next(t["points"] for t in DAILY_TASKS if t["key"] == "checkin")
STREAK_DAYS = MONETIZATION["checkin_streak"]
assert CHECKIN_PTS == 20 and STREAK_DAYS == 30, (CHECKIN_PTS, STREAK_DAYS)

# 1. Markup: button + bubble exist, bubble starts hidden, image vendored.
assert 'id="mascot-wrap"' in HTML
assert 'id="mascot-btn"' in HTML
assert 'src="assets/mascot-head.webp?v=155"' in HTML
assert '<div id="mascot-bubble" hidden>' in HTML
assert 'id="mascot-tip"' in HTML and 'id="mascot-close"' in HTML
assert "Phase 155" in HTML
assert os.path.exists("webapp/assets/mascot-head.webp")
size = os.path.getsize("webapp/assets/mascot-head.webp")
assert size <= 50 * 1024, size
from PIL import Image
im = Image.open("webapp/assets/mascot-head.webp")
assert im.size[0] == 256, im.size
print("markup OK (button + hidden bubble + vendored 256px image, "
      f"{size} bytes)")

# 2. Bubble NEVER opens on its own: mascotShowTip is called exactly
# once in the Phase 155 block — inside the mascot button's onclick.
seg = JS[JS.index("// ---------- Phase 155:"):]
assert seg.count("function mascotShowTip()") == 1
assert seg.count("mascotShowTip();") == 1, "one call site: the tap"
assert '$("mascot-btn").onclick' in seg
assert "hidden = false" in seg
print("no auto-open OK (show only wired to the mascot tap)")

# 3. Tips: 7 of them, rotating, every number true about a live feature.
m = re.search(r"const MASCOT_TIPS = \[(.*?)\];", seg, re.S)
assert m, "MASCOT_TIPS array missing"
tips = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
assert len(tips) == 7, tips
tips = [t.encode().decode("unicode_escape") for t in tips]
assert f"{CHECKIN_PTS} points" in tips[0]
assert f"{STREAK_DAYS} days" in tips[1]
assert "Settings" in tips[2] and "blood donor" in tips[2]
assert "@NexoraSocial_bot" in tips[3] and "caption" in tips[3]
assert "500 m" in tips[4]
assert "10 Stars" in tips[5]
assert "schedule a post" in tips[6] and "composer" in tips[6]
# No invented numbers anywhere in the tips.
nums = set(int(n) for t in tips for n in re.findall(r"\d+", t))
assert nums <= {20, 30, 500, 10}, nums
# Rotation: index advances and wraps with modulo.
assert "mascotTipIdx % MASCOT_TIPS.length" in seg
assert "mascotTipIdx++" in seg
print("tips OK (7 rotating tips, numbers match live config: "
      f"check-in {CHECKIN_PTS}, streak {STREAK_DAYS}, 500 m, 10 Stars)")

# 4. Dismiss: x button hides, tapping elsewhere hides, taps on the
# mascot itself do not bubble-hide it.
assert '$("mascot-close").onclick' in seg
assert "mascotHideTip();" in seg
assert "stopPropagation" in seg
assert "!w.contains(e.target)" in seg
print("dismiss OK (x + tap-elsewhere hide, mascot taps kept)")

# 5. Placement at 360 px: bottom-right above the pill bottom-nav,
# never over the composer or the glassbar; wrap takes no taps itself.
wrap = CSS[CSS.index("#mascot-wrap"):CSS.index("#mascot-wrap") + 400]
assert "position: fixed" in wrap
assert "right: 12px" in wrap and "bottom: 86px" in wrap
assert "pointer-events: none" in wrap
btn = CSS[CSS.index("#mascot-btn {"):]
btn = btn[:btn.index("}")]
assert "width: 48px" in btn and "height: 48px" in btn
assert "border-radius: 50%" in btn
img = CSS[CSS.index("#mascot-btn img"):]
img = img[:img.index("}")]
assert "object-fit: cover" in img and "border-radius: 50%" in img
bub = CSS[CSS.index("#mascot-bubble {"):]
bub = bub[:bub.index("}")]
assert "right: 56px" in bub and "width: 230px" in bub
assert "max-width: calc(100vw - 84px)" in bub
# Geometry at 360 px: bubble left edge 360-56-230 = 74 px (on screen);
# mascot bottom edge 86 px clears the pill nav — the LAST .bottom-nav
# rule that sets bottom wins (bottom: 8px), and the pill is ~46 px tall,
# so its top edge sits ~54 px up. Glassbar lives on the LEFT (left: 8px).
assert 360 - 56 - 230 == 74
nav_bottoms = [int(v) for v in re.findall(
    r"\.bottom-nav\s*\{[^}]*bottom:\s*(\d+)px", CSS)]
assert nav_bottoms, "no .bottom-nav bottom rule found"
assert 86 > nav_bottoms[-1] + 60, nav_bottoms
gb = CSS[CSS.index("#glassbar {"):]
gb = gb[:gb.index("}")]
assert "left: 8px" in gb
comp = CSS[CSS.index(".composer {"):]
comp = comp[:comp.index("}")]
assert "position: fixed" not in comp, "composer must stay in-flow"
print("placement OK (48px circle, bottom 86px clears nav, bubble fits "
      "at 360px, glassbar left / mascot right, composer in-flow)")

# 6. Nexa untouched: the mascot block never mentions Nexa, and the
# Nexa wiring is still there.
assert "exa" not in seg.replace("Phase 155", "").replace("mascot", "")
assert "sendNexa" in JS and "nexa-input" in JS
assert "Nexa" in HTML
print("Nexa untouched OK (mascot is a separate tips helper)")

with TestClient(app) as c:
    assert c.post("/auth",
                  json={"initData": ALICE["X-Init-Data"]}).status_code == 200

    # 7. No new endpoints, no schema change: routes still 158,
    # backup still 43 tables.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 43, len(r.json()["tables"])
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 158, len(paths)
    assert not any("mascot" in p for p in paths), paths
    print("routes 158 + backup 43 tables OK (no new endpoints, no schema change)")

# 8. Neighbours intact.
assert "loadBloodDonors" in JS and "bloodMaybeAskLocation" in JS
assert "openNearby" in JS and "nbLocate" in JS
assert "composer-post" in HTML and "composer-draft" in HTML
assert "glassbar" in HTML
assert "Phase 153" in JS and "Phase 154" in JS
assert "avatarEl(p.author_name, p.author_id, false, p.author_photo)" in JS
assert "museum" not in JS.lower() and "museum" not in HTML.lower()
print("neighbours OK (Blood, Nearby, composer, glassbar, feed photos)")

# 9. Version.
assert HTML.count("?v=155") == 10, HTML.count("?v=155")
assert "?v=15" + "4" not in HTML
assert 'menu_url.rstrip("/") + "/?v=155"' in BOT
print("PHASE 155 OK")
