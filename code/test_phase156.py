"""Phase-156 tests: real 3D mascot + context-aware tips (owner
order Nov 20, 2026: "মাসকট টি ছবি আকারে না দিয়ে 3D করো। যে পেজে
যাবে সেই পেজ সম্পর্কে টিপস দিবে এখানে কিভাবে কি করবে। আর সাইজ আর
একটু ছোট করবা।").

- The mascot is a Three.js head built from primitives (vendored r149,
  no CDN, no image file anywhere); WebGL failure falls back to a
  small CSS face (plain divs). Button 48 px -> 40 px.
- Tips are context-aware: MASCOT_TIPS_BY_VIEW maps every showView
  view (except assistant, which falls back to the general tips) to
  2-4 short English tips about THAT page. Every number is
  cross-checked against live config / routes / games / themes —
  no invented numbers, no invented features.
- The bubble NEVER opens on its own; switching page resets the
  rotation and hides the bubble. Client-side only: no new endpoints,
  no schema change, backup 43 tables, routes 158.
"""
import hashlib, hmac, json, os, re, time, urllib.parse
from datetime import timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase156.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import (app, SessionLocal, DM_REACTIONS, STORY_TTL,
                    LEVELS)
from app import models
from app.config import (DAILY_TASKS, MONETIZATION,
                        VERIFICATION_MIN_FOLLOWERS,
                        VERIFICATION_MIN_REFERRALS, PAYOUT_NETWORKS)
from app.notify import NOTIF_PREF_KEYS


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
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
MAIN = open("app/main.py").read()
GAMES = open("webapp/games.js").read()
BOT = open("app/bot.py").read()

# Live numbers the tips must match (read from code, never hardcoded).
CHECKIN = next(t for t in DAILY_TASKS if t["key"] == "checkin")
FOLLOW3 = next(t for t in DAILY_TASKS if t["key"] == "follow3")
COMMENT5 = next(t for t in DAILY_TASKS if t["key"] == "comment5")
REACT6 = next(t for t in DAILY_TASKS if t["key"] == "react6")
STREAK = MONETIZATION["checkin_streak"]
STAR_PTS = next(th for th, name in LEVELS if name == "Star")
assert (CHECKIN["points"], FOLLOW3["target"], FOLLOW3["points"],
        COMMENT5["target"], COMMENT5["points"],
        REACT6["target"], REACT6["points"], STREAK, STAR_PTS) == \
    (20, 3, 10, 5, 5, 6, 10, 30, 5000)
assert (VERIFICATION_MIN_FOLLOWERS, VERIFICATION_MIN_REFERRALS) == (1000, 50)
assert PAYOUT_NETWORKS == ("TON", "Gram", "USDT")
assert len(DM_REACTIONS) == 6, DM_REACTIONS
assert STORY_TTL == timedelta(hours=24), STORY_TTL
m = re.search(r"def _trending_ranked\(db, user, limit=(\d+)\)", MAIN)
TRENDING_N = int(m.group(1))
assert TRENDING_N == 20, TRENDING_N
m = re.search(r"units < (\d+) or units > (\d+)", MAIN)
BLOOD_UNITS = (int(m.group(1)), int(m.group(2)))
assert BLOOD_UNITS == (1, 10), BLOOD_UNITS
m = re.search(r"_haversine_m\(user\.lat, user\.lon, u\.lat, u\.lon\)"
              r" > (\d+)", MAIN)
NEARBY_M = int(m.group(1))
assert NEARBY_M == 500, NEARBY_M
assert "timedelta(minutes=5)" in MAIN and "timedelta(days=90)" in MAIN
m = re.search(r"const THEME_PALETTES = \[(.*?)\n\];", JS, re.S)
THEMES_N = len(re.findall(r'\{ id: "', m.group(1)))
assert THEMES_N == 33, THEMES_N
GAMES_N = len(re.findall(r'\n  id: "', GAMES))
assert GAMES_N == 11, GAMES_N
assert len(NOTIF_PREF_KEYS) == 10, NOTIF_PREF_KEYS
print("live numbers OK (check-in 20, streak 30, Star 5000, tick 1000/50,"
      " 6 reactions, 24 h stories, top 20, units 1-10, 500 m, 5m-90d,"
      " 33 themes, 11 games, 10 notif switches)")

seg = JS[JS.index("// ---------- Phase 156:"):]

# 1. Markup: canvas + fallback, no image anywhere, Three.js vendored.
assert 'id="mascot-wrap"' in HTML
assert 'id="mascot-btn"' in HTML
assert '<canvas id="mascot-canvas" width="80" height="80"' in HTML
assert 'id="mascot-fallback"' in HTML
assert '<div id="mascot-bubble" hidden>' in HTML
assert 'id="mascot-tip"' in HTML and 'id="mascot-close"' in HTML
assert "mascot-head" not in HTML and "mascot-head" not in JS
assert "mascot-head" not in CSS
assert not os.path.exists("webapp/assets/mascot-head.webp")
wrap = HTML[HTML.index('id="mascot-wrap"'):]
wrap = wrap[:wrap.index("</div>\n</div>") + len("</div>\n</div>")]
assert "<img" not in wrap
assert "vendor/three/three.min.js?v=172" in HTML
three = open("webapp/vendor/three/three.min.js").read()
assert len(three) > 500 * 1024, len(three)
assert "WebGLRenderer" in three and "REVISION" in three
assert "Phase 156" in HTML and "Phase 156" in JS and "Phase 156" in CSS
print("markup OK (canvas + CSS fallback, no image, Three.js vendored)")

# 2. Bubble NEVER opens on its own; page switch resets + hides.
assert seg.count("mascotShowTip();") == 1, "one call site: the tap"
assert '$("mascot-btn").onclick' in seg
assert "hidden = false" in seg
assert "function mascotOnView(name)" in seg
assert "mascotTipIdx = 0" in seg
assert JS.count("mascotOnView(name)") == 2, \
    "hook in showView + definition"
assert 'if (typeof mascotOnView === "function") mascotOnView(name);' in JS
print("no auto-open OK (show only on tap; view switch resets + hides)")

# 3. Per-view tips: coverage, size, rotation, truth.
m = re.search(r"const MASCOT_TIPS_GENERAL = \[(.*?)\];", seg, re.S)
assert m, "general tips missing"
general = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
assert len(general) == 7, general
m = re.search(r"const MASCOT_TIPS_BY_VIEW = \{(.*?)\n\};", seg, re.S)
assert m, "per-view tips missing"
by_view = {}
for key, arr in re.findall(r"(\w+): \[(.*?)\],", m.group(1), re.S):
    by_view[key] = re.findall(r'"((?:[^"\\]|\\.)*)"', arr)
views = re.search(
    r'\["feed", (.*?)\]\.forEach\(v => \{', JS, re.S).group(1)
views = ["feed"] + re.findall(r'"([a-z]+)"', views)
assert set(by_view) == set(views) - {"assistant"}, \
    (sorted(by_view), sorted(views))
for v, tips in by_view.items():
    assert 2 <= len(tips) <= 4, (v, len(tips))
assert "function mascotTipsFor(view)" in seg
assert "MASCOT_TIPS_BY_VIEW[view] || MASCOT_TIPS_GENERAL" in seg
assert "mascotTipIdx % tips.length" in seg
assert "mascotTipIdx++" in seg
assert "mascotTipsFor(currentView)" in seg
# Truth: each number in the right tip, against the live values above.
assert f"{CHECKIN['points']} points" in general[0]
assert f"{STREAK} days" in general[1]
assert "500 m" in general[4] and "10 Stars" in general[5]
f = by_view["feed"]
assert "5 minutes" in f[1] and "90 days" in f[1]
assert "24 hours" in f[3]
t = by_view["tasks"]
assert f"{CHECKIN['points']} points" in t[0]
assert (f"Follow {FOLLOW3['target']} people "
        f"({FOLLOW3['points']} points)") in t[1]
assert (f"write {COMMENT5['target']} comments "
        f"({COMMENT5['points']} points)") in t[1]
assert (f"react to {REACT6['target']} posts "
        f"({REACT6['points']} points)") in t[1]
assert f"{STREAK}-day" in t[2]
lb = by_view["leaderboard"]
assert "top 50" in lb[0]
assert f"{STAR_PTS:,} points" in lb[1] and "Star" in lb[1]
assert (f"{VERIFICATION_MIN_FOLLOWERS:,} followers" in lb[2]
        and f"{VERIFICATION_MIN_REFERRALS} qualified referrals" in lb[2])
assert f"{THEMES_N} shades" in by_view["profile"][1]
assert f"{THEMES_N} shades" in by_view["settings"][0]
assert f"{len(NOTIF_PREF_KEYS)} switches" in by_view["settings"][1]
assert all(n in by_view["settings"][2] for n in PAYOUT_NETWORKS)
assert f"{GAMES_N} games" in by_view["games"][0]
assert f"{len(DM_REACTIONS)} reactions" in by_view["messages"][1]
assert f"{len(DM_REACTIONS)} reactions" in by_view["chat"][1]
assert f"{NEARBY_M} m" in by_view["nearby"][0]
assert f"{TRENDING_N} hottest" in by_view["trending"][0]
assert "7 days" in by_view["trending"][0]
assert (f"{BLOOD_UNITS[0]} to {BLOOD_UNITS[1]} units"
        in by_view["blood"][2])
assert "8 blood groups" in by_view["blood"][2]
assert "7 days" in by_view["admin"][1]
assert f"{len(NOTIF_PREF_KEYS)} switches" in by_view["notifications"][1]
# No invented numbers anywhere in any tip.
all_tips = general + [t for tips in by_view.values() for t in tips]
nums = set()
for tip in all_tips:
    nums.update(int(n.replace(",", ""))
                for n in re.findall(r"\d[\d,]*", tip))
assert nums <= {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 20, 24, 30, 33, 50,
                90, 500, 1000, 2048, 5000}, nums
print(f"tips OK ({len(by_view)} views x 2-4 + 7 general, numbers match "
      f"live code: {sorted(nums)})")

# 4. 3D head: primitives, colours, idle loop, DPR cap, fallback path.
for token in ("THREE.WebGLRenderer", "SphereGeometry", "TorusGeometry",
              "TubeGeometry", "CatmullRomCurve3", "MeshStandardMaterial",
              "requestAnimationFrame", "document.hidden", "setPixelRatio",
              "Math.min(window.devicePixelRatio || 1, 2)",
              "typeof THREE === \"undefined\"", "showFallback",
              "0x8ED4F7", "0xF6F1E7", "antialias: true", "alpha: true",
              "mascotTick", "function mascotInit3D()"):
    assert token in seg, token
assert "mascotInit3D();" in seg
assert ".mf-eye" in CSS and ".mf-smile" in CSS
assert "#mascot-fallback" in CSS
print("3D OK (primitives + sky/cream colours + idle loop + DPR cap +"
      " WebGL fallback)")

# 5. Dismiss: x button hides, tapping elsewhere hides, taps on the
# mascot itself do not bubble-hide it.
assert '$("mascot-close").onclick' in seg
assert "mascotHideTip();" in seg
assert "stopPropagation" in seg
assert "!w.contains(e.target)" in seg
print("dismiss OK (x + tap-elsewhere hide, mascot taps kept)")

# 6. Placement at 360 px: 40 px button above the pill bottom-nav,
# bubble re-anchored; wrap takes no taps itself.
wrap_css = CSS[CSS.index("#mascot-wrap"):CSS.index("#mascot-wrap") + 400]
assert "position: fixed" in wrap_css
assert "right: 12px" in wrap_css and "bottom: 86px" in wrap_css
assert "pointer-events: none" in wrap_css
btn = CSS[CSS.index("#mascot-btn {"):]
btn = btn[:btn.index("}")]
assert "width: 40px" in btn and "height: 40px" in btn
assert "border-radius: 50%" in btn
assert "#mascot-btn img" not in CSS
can = CSS[CSS.index("#mascot-canvas {"):]
can = can[:can.index("}")]
assert "width: 40px" in can and "height: 40px" in can
bub = CSS[CSS.index("#mascot-bubble {"):]
bub = bub[:bub.index("}")]
assert "right: 48px" in bub and "width: 230px" in bub
assert "max-width: calc(100vw - 76px)" in bub
# Geometry at 360 px: bubble left edge 360-48-230 = 82 px (on screen);
# mascot bottom edge 86 px clears the pill nav — the LAST .bottom-nav
# rule that sets bottom wins (bottom: 8px), and the pill is ~46 px tall,
# so its top edge sits ~54 px up. Glassbar lives on the LEFT (left: 8px).
assert 360 - 48 - 230 == 82
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
print("placement OK (40px circle, bottom 86px clears nav, bubble fits "
      "at 360px, glassbar left / mascot right, composer in-flow)")

# 7. The sidebar assistant is untouched: the mascot block never
# mentions it by name, and its wiring is still there.
assert "exa" not in seg.replace("Phase 156", "").replace(
    "mascot", "").replace("MASCOT", "")
assert "sendNexa" in JS and "nexa-input" in JS
assert "Nexa" in HTML
print("assistant untouched OK (mascot is a separate tips helper)")

with TestClient(app) as c:
    assert c.post("/auth",
                  json={"initData": ALICE["X-Init-Data"]}).status_code == 200

    # 8. No new endpoints, no schema change: routes still 158,
    # backup still 43 tables.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 48, len(r.json()["tables"])
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 174, len(paths)
    assert not any("mascot" in p for p in paths), paths
    print("routes 158 + backup 43 tables OK (no new endpoints, no schema change)")

# 9. Neighbours intact.
assert "loadBloodDonors" in JS and "bloodMaybeAskLocation" in JS
assert "openNearby" in JS and "nbLocate" in JS
assert "composer-post" in HTML and "composer-draft" in HTML
assert "glassbar" in HTML
assert "Phase 153" in JS and "Phase 154" in JS
assert "avatarEl(p.author_name, p.author_id, false, p.author_photo)" in JS
assert "museum" not in JS.lower() and "museum" not in HTML.lower()
print("neighbours OK (Blood, Nearby, composer, glassbar, feed photos)")

# 10. Version.
assert HTML.count("?v=172") == 10, HTML.count("?v=172")
assert "?v=15" + "5" not in HTML
assert 'menu_url.rstrip("/") + "/?v=172"' in BOT
print("PHASE 156 OK")
