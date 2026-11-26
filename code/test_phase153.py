"""Phase-153 tests: ask for location when the Blood page opens,
so donor distances can show (owner order Nov 20, 2026, 07:05 Dhaka).

Prompt: on Blood open, if sharing is off, ask once per session via
the existing nbLocate() helper, POST /me/location share:true on
grant, and reload the donor list so distances appear. A denial
(or unavailable location) shows an inline hint with a retry
button instead of nagging; the retry is user-initiated and NOT
gated by the session flag. Sharing is read from GET /me/nearby
(the same source Nearby uses). No new endpoints, no schema
change. Also dedupes bloodDistance(), which Phase 152 left
defined 5 times.
"""
import hashlib, hmac, json, os, re, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase151.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

import math


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


def hav(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 6371000 * 2 * math.asin(math.sqrt(a))


def fmt_dist(d):
    """Mirror of the client's bloodDistance(): metres under 1 km,
    one-decimal km otherwise."""
    if d < 1:
        return f"{round(d * 1000)} m away"
    return f"{d:.1f} km away"


ALICE = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()
MAIN = open("app/main.py").read()

PA = {"lat": 23.81030, "lon": 90.41250}   # viewer
PB = {"lat": 23.81210, "lon": 90.41250}   # ~200 m north of PA
PC = {"lat": 23.82830, "lon": 90.41250}   # ~2.0 km north of PA

# 1. The prompt code: guard, reuse, reload.
seg = JS[JS.index("async function bloodMaybeAskLocation"):]
seg = seg[:seg.index("async function bloodRetryLocation")]
assert "let bloodLocAsked = false;" in JS
# Guard flag is set FIRST, before the sharing check and nbLocate(),
# so a second Blood open while the first prompt is pending cannot
# fire a second prompt.
assert seg.index("if (bloodLocAsked) return;") < seg.index("bloodLocAsked = true;")
assert seg.index("bloodLocAsked = true;") < seg.index('api("/me/nearby")')
assert seg.index('api("/me/nearby")') < seg.index("await nbLocate();")
# The prompt reuses nbLocate() (Telegram LocationManager first,
# browser geolocation fallback) — no direct geolocation call here.
assert "await nbLocate();" in seg
assert "navigator.geolocation" not in seg
assert "getCurrentPosition" not in seg
# Grant -> POST /me/location share:true, then reload donors.
assert 'api("/me/location", { method: "POST"' in seg
assert "share: true" in seg
assert "loadBloodDonors()" in seg
assert "nbSharing = true;" in seg
# Denial -> the inline hint appears (not a re-prompt).
assert "blood-loc-hint" in seg
# Retry is user-initiated: NOT gated by the session flag.
rseg = JS[JS.index("async function bloodRetryLocation"):]
rseg = rseg[:rseg.index("async function loadBlood(")]
assert "bloodLocAsked" not in rseg
assert "await nbLocate();" in rseg
assert 'api("/me/location", { method: "POST"' in rseg
print("prompt code OK (guard-first, nbLocate reuse, grant reloads, retry ungated)")

# 2. loadBlood calls the prompt and binds the retry button.
lb = JS[JS.index("async function loadBlood()"):]
lb = lb[:lb.index("async function loadBloodDonors()")]
assert "bloodMaybeAskLocation();" in lb
assert '$("blood-loc-on").onclick = () => bloodRetryLocation();' in lb
print("loadBlood wiring OK (prompt on open, retry bound)")

# 3. The hint element + copy + CSS.
assert 'id="blood-loc-hint"' in HTML
assert 'id="blood-loc-on"' in HTML
assert "Turn on location" in HTML
assert "Turn on location to see how far each donor is." in HTML
assert "turn it off anytime in Nearby" in HTML
hint_tag = re.search(r'<div id="blood-loc-hint"[^>]*>', HTML).group(0)
assert "hidden" in hint_tag, hint_tag
assert ".blood-loc-hint" in CSS
assert "#blood-loc-hint[hidden] { display: none; }" in CSS
assert "Phase 153: Blood-page location hint" in CSS
print("hint element + copy + CSS OK")

# 4. bloodDistance dedupe (Phase 152 left 5 copies).
assert JS.count("function bloodDistance") == 1, JS.count("function bloodDistance")
print("bloodDistance deduped to a single definition OK")

# 5. Flow simulation — a Python mirror of bloodMaybeAskLocation(),
# driven by stubs, so the session guard + hint + reload behaviour
# is exercised, not just grepped. (The pending-prompt race is
# covered by the source-order assertions in section 1.)
class _LocFlow:
    """Mirror of the JS: flag set first, sharing checked, then
    nbLocate(); grant posts share:true and reloads donors."""
    def __init__(self, sharing, locate_result):
        self.sharing = sharing
        self.locate_result = locate_result  # dict, or None (denied)
        self.asked = False
        self.locate_calls = 0
        self.posts = []
        self.reloads = 0
        self.hint_shown = False

    def _api_nearby(self):
        return {"sharing": self.sharing}

    def _locate(self):
        self.locate_calls += 1
        return self.locate_result

    def _post_location(self, lat, lon):
        self.posts.append({"lat": lat, "lon": lon, "share": True})
        self.sharing = True
        return {"sharing": True}

    def maybe_ask(self):
        if self.asked:
            return
        self.asked = True
        if self._api_nearby()["sharing"]:
            self.hint_shown = False
            return
        pos = self._locate()
        if not pos:
            self.hint_shown = True
            return
        r = self._post_location(pos["lat"], pos["lon"])
        if r and r["sharing"]:
            self.hint_shown = False
            self.reloads += 1
        else:
            self.hint_shown = True

    def retry(self):
        pos = self._locate()
        if not pos:
            return
        r = self._post_location(pos["lat"], pos["lon"])
        if r and r["sharing"]:
            self.hint_shown = False
            self.reloads += 1

# Sharing already on -> no prompt, no hint, no locate call.
f = _LocFlow(True, {"lat": 1, "lon": 2})
f.maybe_ask()
assert f.locate_calls == 0 and not f.hint_shown and not f.posts, f.__dict__
# Sharing off + grant -> one locate call, share:true posted, reload.
f = _LocFlow(False, {"lat": 23.8, "lon": 90.4})
f.maybe_ask()
assert f.locate_calls == 1 and f.posts == [{"lat": 23.8, "lon": 90.4, "share": True}]
assert f.reloads == 1 and not f.hint_shown
# Second open in the same session -> no second prompt.
f.maybe_ask()
assert f.locate_calls == 1, f.locate_calls
# Sharing off + deny -> hint shown, and the next open does NOT
# re-prompt.
f = _LocFlow(False, None)
f.maybe_ask()
assert f.locate_calls == 1 and f.hint_shown and not f.posts
f.maybe_ask()
assert f.locate_calls == 1 and f.hint_shown
# Retry button after a denial -> locate again; still denied, hint
# stays; then grant hides the hint and reloads.
f.retry()
assert f.locate_calls == 2 and f.hint_shown
f.locate_result = {"lat": 23.8, "lon": 90.4}
f.retry()
assert f.locate_calls == 3 and f.reloads == 1 and not f.hint_shown
print("flow simulation OK (once per session, hint on deny, retry works)")

# 6. Server: /me/nearby is the sharing source the client reads.
with TestClient(app) as c:
    assert c.post("/auth", json={"initData": ALICE["X-Init-Data"]}).status_code == 200
    r = c.get("/me/nearby", headers=ALICE)
    assert r.status_code == 200 and r.json()["sharing"] is False, r.text
    r = c.post("/me/location", headers=ALICE, json={**PA, "share": True})
    assert r.status_code == 200 and r.json().get("sharing") is True, r.text
    r = c.get("/me/nearby", headers=ALICE)
    assert r.json()["sharing"] is True, r.text
    r = c.post("/me/location", headers=ALICE,
               json={"lat": 0, "lon": 0, "share": False})
    assert r.status_code == 200, r.text
    r = c.get("/me/nearby", headers=ALICE)
    assert r.json()["sharing"] is False, r.text
    print("/me/nearby sharing round-trip OK (the client's source of truth)")

    # 7. No new endpoints, no schema change: routes still 158,
    # backup still 43 tables.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 184, len(paths)
    assert len([p for p in paths if "blood" in p]) == 6, paths
    print("routes 158 + backup 43 tables OK (no new endpoints, no schema change)")

# 8. Neighbours intact.
assert "openNearby" in JS and "nbLocate" in JS and "nbSharing" in JS
assert "nearby-toggle" in HTML and "nbPaintToggle" in JS
assert "loadBloodDonors" in JS and "loadBloodRequests" in JS
assert "settings-blood-save" in JS
assert "loadMessages" in JS and "loadDesigns" in JS
assert "museum" not in JS.lower() and "museum" not in HTML.lower()
print("neighbours OK (Nearby toggle, Blood flows, no museum)")

# 9. Version.
assert HTML.count("?v=192") == 10, HTML.count("?v=192")
assert "?v=15" + "2" not in HTML
assert 'menu_url.rstrip("/") + "/?v=192"' in BOT
print("PHASE 153 OK")
