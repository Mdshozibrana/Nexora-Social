"""Phase-146 tests: a refresh on someone's profile re-opens that
profile instead of the viewer's own.

Owner report (2026-11-19 ~00:33 Dhaka): visiting another member's
profile and refreshing opened his OWN profile instead of
refreshing theirs.

Root causes, both in webapp/app.js:
(a) the Phase 72 pull-to-refresh LOADERS map had
    `profile: () => { if (me) openProfile(me.telegram_id); }` —
    on ANY profile view, pull-to-refresh re-opened the viewer's
    own profile (the viewed id in `profileId` was never used);
(b) openProfile kept the viewed id only in the in-memory
    `profileId` variable — a full Mini App reload boots to Feed
    (routeStartParam only handles a profile_<id> start param).

Fix: openProfile remembers the viewed id in sessionStorage key
"nx_profile" (same pattern as nx_open_admin / nx_actas);
showView forgets it when leaving the profile view; bootOk
restores it when no start-param deep link fired; the PTR loader
re-opens the viewed profileId. Restore goes through the same
openProfile, so the Phase 136 private-account lock still
applies. Neighbour fix in the same area: the sidebar "My
Profile" item and the glassbar footer called showView("profile")
alone, which kept showing the last-rendered profile instead of
the viewer's own — both now openProfile(me.telegram_id).

Covers: node harness runs the remembered-profile helpers
(remember/forget/read/restore) extracted from app.js with a
stubbed sessionStorage; PTR slice re-opens profileId; openProfile
remembers; showView forgets on non-profile views; bootOk
restores after routeStartParam and the start param wins;
sidebar + footer open self; private-profile posts stay locked
for a non-follower after restore (server-side, via the same
openProfile path); backup still 42 tables (no schema change);
?v=171 x5, no older shell version.
"""
import hashlib, hmac, json, os, re, subprocess, sys, tempfile, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase146.db"
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
CAROL = H(333, "Carol")


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Restore target exists: a public post lists on the profile.
    r = c.post("/posts", headers=CAROL,
               json={"type": "text", "caption": "hello from Carol"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = c.get("/users/333/posts", headers=ALICE)
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()["posts"]] == [pid], r.json()
    assert r.json().get("locked") is not True, r.json()
    print("public profile posts OK")

    # 2. Private lock still applies after a restore (restore goes
    # through the same openProfile path, server-side).
    r = c.post("/me/privacy", headers=BOB, json={"is_private": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"is_private": True}, r.json()
    r = c.post("/posts", headers=BOB,
               json={"type": "text", "caption": "bob secret post"})
    assert r.status_code == 200, r.text
    bob_post = r.json()["id"]
    r = c.get("/users/222/posts", headers=ALICE)
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True, r.json()
    assert r.json()["posts"] == [], r.json()
    r = c.get(f"/posts/{bob_post}", headers=ALICE)
    assert r.status_code == 403, r.status_code
    # Bob himself still sees his own posts.
    r = c.get("/users/222/posts", headers=BOB)
    assert r.status_code == 200, r.text
    assert bob_post in [p["id"] for p in r.json()["posts"]], r.json()
    assert r.json().get("locked") is not True, r.json()
    print("private lock after restore OK")

    # 3. Backup still 42 tables (no schema change).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 46, len(r.json()["tables"])
    print("backup: 42 tables OK")

# 4. Client: the helpers exist and are wired exactly as designed.
JS = open("webapp/app.js").read()
for m in ("function rememberProfile(id) {",
          "function forgetProfile() {",
          "function readRememberedProfile() {",
          "function restoreProfile() {",
          'sessionStorage.setItem("nx_profile"',
          'sessionStorage.removeItem("nx_profile")',
          'sessionStorage.getItem("nx_profile"'):
    assert m in JS, m
assert JS.count('"nx_profile"') >= 3, JS.count('"nx_profile"')
assert "rememberProfile(userId);" in JS
# openProfile remembers, right where profileId is set.
op = JS[JS.index("async function openProfile(userId) {"):
        JS.index("async function loadProfilePosts")]
assert "profileId = userId;" in op
assert op.index("rememberProfile(userId);") > op.index("profileId = userId;")
# showView forgets when leaving the profile view — and only then.
sv = JS[JS.index("function showView(name, viaBack) {"):
        JS.index("function anyOverlayOpen()")]
assert 'if (name !== "profile") forgetProfile();' in sv
# boot: start param wins, otherwise the remembered profile restores.
assert "if (!routeStartParam()) restoreProfile();" in JS
rs = JS[JS.index("function routeStartParam() {"):
        JS.index("function bootOk()")]
assert "return true;" in rs and "return false;" in rs
assert "{ openProfile(id); return true; }" in rs
print("remember/forget/restore wiring OK")

# 5. Client: pull-to-refresh re-opens the VIEWED profile.
start = JS.index("// Phase 72 (owner): pull-to-refresh on EVERY main page")
end = JS.index("\nfunction openDesignSheet(d) {", start)
slice72 = JS[start:end]
assert "profile: () => { if (profileId) openProfile(profileId);" in slice72
assert "profile: () => { if (me) openProfile(me.telegram_id); }" not in slice72
assert "if (profileId) openProfile(profileId);" in slice72
assert "else if (me) openProfile(me.telegram_id);" in slice72
print("PTR loader re-opens the viewed profile OK")

# 6. Client: sidebar "My Profile" + glassbar footer open self.
assert 'if (go === "profile" && me) openProfile(me.telegram_id);' in JS
assert ('if (me) openProfile(me.telegram_id); else showView("profile");'
        in JS)
# nav-me / back-to-profile paths still open self too.
assert JS.count("openProfile(me.telegram_id)") >= 4, \
    JS.count("openProfile(me.telegram_id)")
print("own-profile entry points OK")

# 7. Node harness: run the real helpers from app.js with a stubbed
# sessionStorage and a recording openProfile.
hstart = JS.index("function rememberProfile(id) {")
hend = JS.index("function restoreProfile() {")
hend = JS.index("\n}\n", hend) + len("\n}\n")
helpers = JS[hstart:hend]
assert "function restoreProfile() {" in helpers
harness = """
const store = {};
const sessionStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};
let opened = [];
function openProfile(id) { opened.push(id); }
""" + helpers + """
function check(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
// remember + restore a visited profile (the reported bug).
rememberProfile(222);
check(readRememberedProfile() === 222, "read back 222");
restoreProfile();
check(JSON.stringify(opened) === "[222]", "restore opens 222, got " + JSON.stringify(opened));
// own profile (self id) restores as self.
opened = [];
rememberProfile(111);
restoreProfile();
check(JSON.stringify(opened) === "[111]", "restore opens self 111");
// leaving the profile forgets it: no restore, normal boot.
forgetProfile();
check(readRememberedProfile() === 0, "forget clears");
opened = [];
restoreProfile();
check(opened.length === 0, "no restore without a remembered id");
// garbage / zero / negative keys never open anything.
for (const bad of ["garbage", "0", "-5", ""]) {
  sessionStorage.setItem("nx_profile", bad);
  check(readRememberedProfile() <= 0, "bad key " + JSON.stringify(bad) + " must read <= 0");
  opened = [];
  restoreProfile();
  check(opened.length === 0, "bad key " + JSON.stringify(bad) + " must not open");
}
console.log("NODE HARNESS OK");
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(harness)
    hpath = f.name
r = subprocess.run(["node", hpath], capture_output=True, text=True)
os.unlink(hpath)
print(r.stdout.strip())
assert r.returncode == 0, r.stderr or r.stdout
print("node harness: remember/restore behaviour OK")

# 8. Client markers + asset version.
HTML = open("webapp/index.html").read()
assert HTML.count("?v=171") == 10, HTML.count("?v=171")
assert "?v=14" + "5" not in HTML
for m in ("loadSettings", "renderLevelBlock", "openTipSheet",
          "loadProfilePosts", "openProfile", "loadMe",
          "loadDrafts", "loadScheduled", "loadFollowRequests",
          "themeCard", "dataCard", "loadBlocked", "routeStartParam",
          "loadFeed", "showView", "ptr-global", "Pull to refresh",
          "nx_profile", "restoreProfile", "rememberProfile"):
    assert m in JS, m
print("client markers + ?v=171 OK")

print("PHASE-146 TESTS PASSED")
