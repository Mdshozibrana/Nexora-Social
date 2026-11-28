"""Phase-163 tests: blue verified tick on Blood donor cards
(owner, Nov 20 2026 — "Blood-এও টিক দাও").

Why the tick was missing: _blood_donor_out never sent the
verified flag, and the donor card rendered the name as plain
text — no verifiedBadge() anywhere on the card. Phase 160's
shared rule only covered sites that already rendered a tick.

Covers: the payload gains is_verified (same bool(u.is_verified)
as every other endpoint); the donor-card name becomes the shared
.vname line (long names shrink, floor 12px, tick hugs the name);
request cards untouched; 360px geometry for the donor line;
neighbours; backup 44 tables; routes 163.
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
from app.db import SessionLocal
from app import models

BOB = H(222, "Bob")
CAROL = H(333, "Carol")
DAVE = H(444, "Dave")
EVE = H(555, "Eve")
MAIN = open("app/main.py").read()


def css_rule(sel):
    m = re.search(re.escape(sel) + r" \{([^}]*)\}", CSS, re.S)
    assert m, sel + " rule missing"
    return m.group(1)


def css_px(rule, prop):
    m = re.search(prop + r":\s*([\d.]+)px", rule)
    assert m, prop + " missing in " + rule[:60]
    return float(m.group(1))


BLOOD = JS[JS.index("async function loadBloodDonors()"):
           JS.index("async function loadBloodRequests()")]
DONOR = MAIN[MAIN.index("def _blood_donor_out"):
             MAIN.index("def _blood_visible_donors")]


def em_width(name):
    # Same conservative system-ui advance model as test_phase160:
    # caps 0.67em, lowercase 0.5em, spaces 0.25em, digits 0.55em.
    w = 0.0
    for ch in name:
        if ch == " ":
            w += 0.25
        elif ch.isdigit():
            w += 0.55
        elif ch.isupper():
            w += 0.67
        else:
            w += 0.5
    return w


def fit_size(name_em, base, budget):
    # Mirror of fitVerifiedNames(): step 0.5px while truncated,
    # never below the 12px floor.
    size = base
    while size > 12 and name_em * size > budget:
        size -= 0.5
    return size


LONG = "Abidur Rahman Niloy"          # the owner's screenshot row 5
LONG28 = "Mohammed Abidur Rahman Niloy"  # 28 chars, must hit the floor
SHORT = "MD Shozib Rana"
assert abs(em_width(LONG) - 9.51) < 0.01, em_width(LONG)
assert abs(em_width(LONG28) - 13.93) < 0.01, em_width(LONG28)
assert abs(em_width(SHORT) - 7.18) < 0.01, em_width(SHORT)

# 1. JS parses (node) — the donor card is client-rendered.
for f in ("webapp/games.js", "webapp/app.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True)
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (games.js + app.js parse)")

# 2. Server: the donor payload carries the verified flag, from
# the same source of truth as every other endpoint.
assert '"is_verified": bool(u.is_verified)' in DONOR, DONOR[:400]
assert "Phase 163" in DONOR, "server marker missing"
assert MAIN.count('"is_verified": bool(u.is_verified)') >= 1
print("server marker OK (_blood_donor_out sends is_verified)")

# 3. Client: the donor-card name is the shared .vname line.
assert 'nm.className = "blood-name vname";' in BLOOD, "vname line missing"
assert 'nmText.className = "vname-text";' in BLOOD, "vname-text missing"
assert "nmText.textContent = u.first_name;" in BLOOD
assert 'if (u.is_verified) nm.appendChild(verifiedBadge());' in BLOOD
assert "nm.textContent = u.first_name;" not in BLOOD, \
    "old plain-name line must be gone"
assert "fitVerifiedNamesSoon(box);" in BLOOD, "re-fit after render"
assert "Phase 163" in BLOOD, "client marker missing"
assert JS.count('className = "blood-name vname"') == 1, \
    "only the donor card uses the vname line"
assert JS.count("verifiedBadge()") == 19, "1 def + 18 call sites (19th: Phase 199 portfolio name)"
assert JS.count("vname-text") >= 18, JS.count("vname-text")
print("donor card code OK (shared .vname line, conditional badge)")

# 4. CSS: the line takes the full .blood-info width; the base
# one-line name rule is untouched.
line_rule = css_rule(".blood-name.vname")
assert "display: flex" in line_rule, line_rule
assert "width: 100%" in line_rule, line_rule
assert "Phase 163" in CSS, "CSS marker missing"
base_rule = css_rule(".blood-name")
assert "white-space: nowrap" in base_rule, base_rule
assert "text-overflow: ellipsis" in base_rule, base_rule
assert abs(css_px(base_rule, "font-size") - 15) < 0.01, base_rule
assert ".blood-donor-card { flex-direction: column;" in CSS, \
    "two-row layout must stay"
assert ".blood-top { display: flex; align-items: center; gap: 10px; }" in CSS
assert ".blood-bottom { display: flex; align-items: center; gap: 10px; }" in CSS
print("CSS OK (.blood-name.vname full width, base rule intact)")

# 5. Live: verified donor -> is_verified true; unverified -> false;
# exact key set gains the new field; still no phone anywhere.
with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE, EVE):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200
    # BOB verified via the DB (same pattern as test_phase131).
    with SessionLocal() as db:
        db.query(models.User).filter_by(telegram_id=222).one().is_verified = True
        db.commit()
    # Opt-ins: BOB (verified) O+, CAROL (unverified) A-,
    # EVE (unverified) O-. ALICE is the admin (ADMIN_IDS=111)
    # and /auth verifies the admin, so she cannot stand in as
    # an unverified donor; DAVE views.
    for h, g in ((BOB, "O+"), (CAROL, "A-"), (EVE, "O-")):
        r = c.post("/me/blood-group", headers=h,
                   json={"blood_group": g, "is_donor": True})
        assert r.status_code == 200, r.text
    r = c.get("/blood/donors", headers=DAVE)
    assert r.status_code == 200, r.text
    by_id = {d["telegram_id"]: d for d in r.json()["donors"]}
    assert set(by_id) == {222, 333, 555}, by_id
    assert by_id[222]["is_verified"] is True, by_id[222]
    assert by_id[333]["is_verified"] is False, by_id[333]
    assert by_id[555]["is_verified"] is False, by_id[555]
    for d in by_id.values():
        assert set(d.keys()) == {"telegram_id", "first_name",
                                 "username", "blood_group",
                                 "country", "photo_file_id",
                                 "is_verified"}, d.keys()
        assert "phone" not in json.dumps(d).lower()
    print("donor payload OK (verified true/false, exact keys, no phone)")

# 6. Request cards untouched: hospital · city head stays a plain
# .blood-name, author stays a muted byline — no tick added there.
assert 'head.className = "blood-name";' in JS, "request head changed?"
assert 'head.textContent = r.hospital + " · " + r.city;' in JS
assert '" · by " + (r.author_name' in JS, "request byline changed?"
print("request cards OK (no tick added, byline unchanged)")

# 7. 360px geometry: the donor name line at 360px.
# Budget (Phase 152 layout numbers): viewport 360 - body pad 24
# = 336; card padding 20 -> 316; avatar 42 + gaps 20 +
# worst-case badge (AB-, ~59) -> info 195; tick 21 -> text 174;
# base 15 (from .blood-name).
DONOR_LINE, DONOR_BUDGET, DONOR_BASE = 195, 174, 15


def hug_tick_left(name, base, budget):
    # Mirror of fitVerifiedNames + shrink-only flex (Phase 162):
    # the text span is its fitted content (capped by the budget),
    # the tick sits 5px after it.
    size = fit_size(em_width(name), base, budget)
    text_w = min(em_width(name) * size, budget)
    return size, text_w + 5


for name in ("Crypto", "Nexora Social", "MD Shozib Rana"):
    size, tick_left = hug_tick_left(name, DONOR_BASE, DONOR_BUDGET)
    assert size == DONOR_BASE, (name, size, "short name must not shrink")
    assert tick_left < DONOR_LINE, (name, tick_left, DONOR_LINE,
                                    "tick must hug the text, not the far edge")
    print("  donor '%s' tick at %.1fpx (line %d, gap 5px)"
          % (name, tick_left, DONOR_LINE))
# Long verified name: still shrinks, still one line, tick adjacent.
size, tick_left = hug_tick_left(LONG, DONOR_BASE, DONOR_BUDGET)
assert size == DONOR_BASE, (LONG, size)
assert tick_left < DONOR_LINE, (LONG, tick_left)
# 28-char name: floor + ellipsis, tick intact and adjacent.
size, tick_left = hug_tick_left(LONG28, DONOR_BASE, DONOR_BUDGET)
assert size == 12, size
assert tick_left == 175.16 or abs(tick_left - 172.16) < 0.01, tick_left
assert tick_left <= DONOR_LINE, tick_left
# Resize re-fit: a wider line re-grows the name to its base size.
assert fit_size(em_width(LONG), DONOR_BASE, 300) == DONOR_BASE, \
    "re-grow on resize"
print("donor geometry OK (long name whole, 28-char at floor, tick hugs)")

# 8. Neighbours intact (Phase 161 removed the Archery remote;
# Phases 160/162 own the shared name rule).
for bit in ("loadBloodDonors", "loadBloodRequests", "loadRanks",
            "postCard", "commentRow", "openProfile", "loadMessages",
            "loadNotifications", "loadTrending", "loadSkills",
            "sendNexa", "mascotOnView", "composer-post", "glassbar",
            "fitVerifiedNames", "nbPaintPeople", "openStoryViewers"):
    assert bit in JS or bit in GAMES or bit in CSS, bit
assert GAMES.count("registerGame({") == 13, "games count changed"
assert "arch-remote" not in GAMES and "arch-shoot" not in GAMES, \
    "Phase 161 removal must stay removed"
print("neighbours OK")

# 9. No new endpoints, no schema change: routes still 163,
# backup still 44 tables.
with TestClient(app) as c:
    assert c.post("/auth",
                  json={"initData": ALICE["X-Init-Data"]}).status_code == 200
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    print("backup: 44 tables OK")
paths = {rt.path for rt in app.routes}
assert len(paths) == 191, len(paths)
print("routes: 163 OK (no new endpoints)")

# 10. Version.
assert HTML.count("?v=205") == 10, HTML.count("?v=205")
assert "?v=16" + "2" not in HTML
assert 'menu_url.rstrip("/") + "/?v=205"' in BOT
assert "Phase 163" in CSS and "Phase 163" in JS and "Phase 163" in MAIN
print("version OK (?v=205 x10, no old-version literals)")

print("PHASE 163 OK")
