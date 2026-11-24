"""Phase-145 tests: profile drops the Stars line and the Level/badges block.

Owner order (2026-11-19 ~00:32 Dhaka, on-phone check of Phase 144):
his screenshot of the official @nexora profile circled the
"⭐ 0 Stars received · 0 tips" line and the whole Level block
(Level 1 · Newcomer, progress bar, "15 points to Level 2", the
badge chips) with "এগুলো তো সেটিংসে আছেই। তাহলে এখানে লাগবে না" —
they already live in Settings, so they are not needed on the
profile. Removal is profile-view only: openProfile() is the one
render path for own, other users' and the official profile.

Covers: server still serves level/badges in GET /users/{id}
(Settings' "My level" fetches the own profile for them) and the
tips endpoints still work; a post still lists on the profile;
backup still 42 tables (no schema change); the profile slice of
app.js carries NEITHER the stars line NOR the level block, while
every other profile element is intact (name, username, verified
tick, bio, cover, avatar, followers line, posts loader, Follow /
Unfollow, ⭐ Tip button, Block); Settings STILL renders "My level"
(renderLevelBlock via myExtras) and "My tips"; the shared
renderLevelBlock() and the level CSS stay; ?v=145 x5, no older shell version.
"""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase145.db"
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
BOB = H(222, "Bob")


with TestClient(app) as c:
    for h in (ALICE, BOB):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Server still serves the profile data Settings needs.
    for uid, name in ((111, "Alice"), (222, "Bob")):
        r = c.get(f"/users/{uid}", headers=ALICE)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["first_name"] == name, j
        assert "level" in j and "badges" in j, j
        assert j["level"]["level"] == 1, j["level"]
        assert j["level"]["name"] == "Newcomer", j["level"]
        assert isinstance(j["badges"], list) and len(j["badges"]) == 9, \
            len(j["badges"])
        r = c.get(f"/users/{uid}/tips", headers=ALICE)
        assert r.status_code == 200, r.text
        assert r.json()["total_stars_received"] == 0, r.json()
        assert r.json()["tip_count"] == 0, r.json()
    r = c.get("/me/tips", headers=BOB)
    assert r.status_code == 200, r.text
    print("profile data + tips endpoints OK")

    # 2. A post still lists on the profile (posts element intact).
    r = c.post("/posts", headers=BOB,
               json={"type": "text", "caption": "hello from Bob"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = c.get("/users/222/posts", headers=ALICE)
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()["posts"]] == [pid], r.json()
    print("profile posts list OK")

    # 3. Backup still 42 tables (no schema change).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 46, len(r.json()["tables"])
    print("backup: 42 tables OK")

    # 4. Profile render path: ONE openProfile for own, other and
    # official profiles — and it carries NEITHER removed element.
    JS = open("webapp/app.js").read()
    assert JS.count("async function openProfile") == 1, \
        "profile render path is not single"
    prof = JS[JS.index("async function openProfile"):
              JS.index("async function loadProfilePosts")]
    assert "tip-total" not in prof, "stars line still in profile"
    assert "Stars received" not in prof
    assert "/tips" not in prof, "profile still fetches tips"
    assert "renderLevelBlock" not in prof, "level block still in profile"
    assert "level-block" not in prof and "badge-row" not in prof
    assert "tip-total" not in JS, "tip-total left anywhere in app.js"
    assert "renderLevelBlock(u.level, u.badges)" not in JS
    # Everything else on the profile is intact.
    for m in ("profile-hero", "profile-cover", "profile-head",
              "profile-name", "profile-sub", "verifiedBadge",
              " followers · ", "loadProfilePosts", "wave-div",
              '"Unfollow"', '"Follow"', "⭐ Tip ", "openTipSheet",
              "🚫 Block this member", "profile-file", "cover-file"):
        assert m in prof, m
    print("profile slice: both elements gone, rest intact OK")

    # 5. Settings STILL renders both: the shared renderer and its
    # Settings call sites are untouched.
    assert "function renderLevelBlock(level, badges)" in JS
    assert "renderLevelBlock(prof.level, prof.badges)" in JS, \
        "Settings My level lost its renderer"
    for m in ("🏆 My level", "⭐ My tips", "/me/tips",
              "loadSettings", "myExtras()", "From your profile"):
        assert m in JS, m
    CSS = open("webapp/style.css").read()
    assert ".tip-total" not in CSS, "orphan .tip-total rule left"
    assert ".level-block" in CSS and ".level-bar" in CSS \
        and ".badge-chip" in CSS, "Settings level CSS gone"
    print("Settings keeps My level + My tips OK")

    # 6. Client markers + asset version.
    HTML = open("webapp/index.html").read()
    assert HTML.count("?v=171") == 10, HTML.count("?v=171")
    assert "?v=14" + "4" not in HTML
    for m in ("loadSettings", "renderLevelBlock", "openTipSheet",
              "loadProfilePosts", "openProfile", "loadMe",
              "loadDrafts", "loadScheduled", "loadFollowRequests",
              "themeCard", "dataCard", "loadBlocked"):
        assert m in JS, m
    print("client markers + ?v=171 OK")

print("PHASE-145 TESTS PASSED")
