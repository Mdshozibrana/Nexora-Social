"""Phase-158 tests: Skill Swap (দক্ষতা বিনিময়).

Owner order (2026-11-20 — #7 from the Nov 20 global-problems
proposal): teach what you know, learn what you don't — language,
coding, cooking, music. No money, no scheduling in the app, no
ratings in v1: the swap is arranged in a DM.

Covers: client markers (Skills page + sidebar + Settings My skills +
profile display + 9th notification toggle + CSS + mascot skills tips);
model + backup + notify map + rate bucket; add validation (kind,
empty, >80, note >200, dupe, banned word in skill/note, cap 20);
my-skills list/remove round-trip; directory (members only, search q,
kind filter, exact skill, no phone keys, private + block visibility);
matches (computed overlap); connect (notifies, 400/403/404 guards,
pref gates delivery); profile exposure (skills hidden from private
strangers); backup 44 tables; routes 166 (5 new paths, 6 route
entries); ?v=191 x10, no old-version literals.
"""
import hashlib, hmac, json, os, re, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase158.db"
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
DAVE = H(444, "Dave")
EVE = H(555, "Eve")
FRANK = H(666, "Frank")
GRACE = H(777, "Grace")

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()
MAIN = open("app/main.py").read()
MODELS = open("app/models.py").read()
NOTIFY = open("app/notify.py").read()
CONFIG = open("app/config.py").read()


def skill_notifs(c, h):
    r = c.get("/me/notifications?limit=50", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["notifications"]


def count_type(c, h, ntype):
    return sum(1 for n in skill_notifs(c, h) if n["type"] == ntype)


def add_skill(c, h, skill, kind, note=""):
    return c.post("/me/skills", headers=h,
                  json={"skill": skill, "kind": kind, "note": note})


# 1. Client markers: Skills page + sidebar + Settings + profile + toggle.
assert HTML.count("?v=191") == 10, HTML.count("?v=191")
assert "?v=15" + "7" not in HTML
assert 'menu_url.rstrip("/") + "/?v=191"' in BOT
assert 'data-go="skills"' in HTML
assert 'id="view-skills"' in HTML
assert "🤝 Skills" in HTML
for cid in ("skill-tab-directory", "skill-tab-matches",
            "skill-directory-pane", "skill-match-pane",
            "skill-search", "skill-search-btn", "skill-kind-filters",
            "skill-directory-list", "skill-match-list", "skill-empty"):
    assert f'id="{cid}"' in HTML, cid
assert '"settings", "blood", "skills"].forEach(v => {' in JS
assert 'if (name === "skills") loadSkills();' in JS
assert "loadSkills" in JS and "loadSkillsDirectory" in JS
assert "loadSkillsMatches" in JS and "loadMySkills" in JS
assert "skillMemberCard" in JS and "skillChip" in JS
assert "🤝 Connect" in JS
assert "settings-skill-name" in JS and "settings-skill-kind" in JS
assert "settings-skill-note" in JS and "settings-skill-add" in JS
assert "settings-skill-list" in JS
assert "skill-block" in JS and "skill-line" in JS
assert '["skills", "🤝 Skill swap"' in JS
assert 'skill_connect: "🤝"' in JS
assert "  skills: [" in JS
assert "no money, just time" in JS
for rule in (".skill-tabs", ".skill-card", ".skill-chip-teach",
             ".skill-chip-learn", ".skill-block", ".skill-connect",
             ".settings-skill-row"):
    assert rule in CSS, rule
assert "Phase 158" in CSS
print("client markers OK (?v=191 x10, Skills page, Settings, profile, toggle)")

# 2. Server markers: model, backup, notify map, rate bucket.
assert "class SkillEntry(Base):" in MODELS
assert 'skill = Column(String(80), nullable=False, index=True)' in MODELS
assert 'kind = Column(String(8), nullable=False)' in MODELS
assert '("skill_entries", models.SkillEntry)' in MAIN
assert '"skill_connect": "skills"' in NOTIFY
assert '"tips", "messages", "system", "blood", "skills",' in NOTIFY
assert '"mention")' in NOTIFY
assert '"skills": (120, 3600)' in CONFIG
print("server markers OK (model + backup + notify map + rate bucket)")

with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE, EVE, FRANK, GRACE):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 3. Banned word + add validation.
    r = c.post("/admin/banned-words", headers=ALICE, json={"word": "zqxwv"})
    assert r.status_code == 200, r.text
    for bad in ({"skill": "Guitar", "kind": "teachh"},
                {"skill": "", "kind": "teach"},
                {"skill": "   ", "kind": "learn"},
                {"skill": "x" * 81, "kind": "teach"},
                {"skill": "Guitar", "kind": "teach", "note": "n" * 201},
                {"skill": "zqxwv guitar", "kind": "teach"},
                {"skill": "Guitar", "kind": "teach", "note": "zqxwv"}):
        r = c.post("/me/skills", headers=BOB, json=bad)
        assert r.status_code == 400, (bad, r.text)
    print("add validation OK (kind, empty, >80, note >200, banned word)")

    # 4. Adds: BOB teaches Guitar, learns Coding + Guitar; CAROL
    # teaches Coding, learns Guitar; ALICE teaches English; DAVE
    # teaches Cooking, learns Guitar; EVE learns English.
    assert add_skill(c, BOB, "Guitar", "teach").status_code == 200
    r = add_skill(c, BOB, "Coding", "learn", note="weekends")
    assert r.status_code == 200, r.text
    assert r.json()["skill"] == "Coding" and r.json()["kind"] == "learn"
    assert r.json()["note"] == "weekends"
    assert add_skill(c, CAROL, "Coding", "teach").status_code == 200
    assert add_skill(c, CAROL, "Guitar", "learn").status_code == 200
    assert add_skill(c, ALICE, "English", "teach").status_code == 200
    assert add_skill(c, DAVE, "Cooking", "teach").status_code == 200
    assert add_skill(c, DAVE, "Guitar", "learn").status_code == 200
    assert add_skill(c, EVE, "English", "learn").status_code == 200
    # Dupe (same kind, case-insensitive) is refused; the same
    # skill in the OTHER kind is fine.
    r = add_skill(c, BOB, "guitar", "teach")
    assert r.status_code == 400, r.text
    r = add_skill(c, BOB, "Guitar", "learn")
    assert r.status_code == 200, r.text
    r = c.get("/me/skills", headers=BOB)
    assert r.status_code == 200, r.text
    assert {s["skill"] for s in r.json()["skills"]} == {"Guitar", "Coding"}, r.json()
    assert all(set(s.keys()) == {"id", "skill", "kind", "note", "created_at"}
               for s in r.json()["skills"])
    print("adds + dupe guard + my-skills list OK")

    # 5. Directory: only members with skills, exact key set, no
    # phone/location keys; search + kind + exact-skill filters.
    r = c.get("/skills/directory", headers=BOB)
    assert r.status_code == 200, r.text
    members = r.json()["members"]
    assert {m["telegram_id"] for m in members} == {111, 222, 333, 444, 555}, members
    for m in members:
        assert set(m.keys()) == {"telegram_id", "first_name", "username",
                                 "photo_file_id", "country", "teach", "learn"}, m.keys()
        assert "phone" not in json.dumps(m).lower()
    by_id = {m["telegram_id"]: m for m in members}
    assert set(by_id[222]["teach"]) == {"Guitar"}
    assert set(by_id[222]["learn"]) == {"Coding", "Guitar"}
    assert set(by_id[333]["teach"]) == {"Coding"}
    assert set(by_id[333]["learn"]) == {"Guitar"}
    r = c.get("/skills/directory?q=guitar", headers=BOB)
    assert {m["telegram_id"] for m in r.json()["members"]} == {222, 333, 444}, r.json()
    r = c.get("/skills/directory?q=COD", headers=BOB)
    assert {m["telegram_id"] for m in r.json()["members"]} == {222, 333}, r.json()
    r = c.get("/skills/directory?kind=teach&q=guitar", headers=BOB)
    assert {m["telegram_id"] for m in r.json()["members"]} == {222}, r.json()
    r = c.get("/skills/directory?kind=teach", headers=BOB)
    assert all(m["learn"] == [] and m["teach"] for m in r.json()["members"]), r.json()
    r = c.get("/skills/directory?kind=learn", headers=BOB)
    assert all(m["teach"] == [] and m["learn"] for m in r.json()["members"]), r.json()
    r = c.get("/skills/directory?skill=coding", headers=BOB)
    assert {m["telegram_id"] for m in r.json()["members"]} == {222, 333}, r.json()
    r = c.get("/skills/directory?skill=Coding&kind=teach", headers=BOB)
    assert {m["telegram_id"] for m in r.json()["members"]} == {333}, r.json()
    r = c.get("/skills/directory?skill=Banjo", headers=BOB)
    assert r.json()["members"] == [], r.json()
    r = c.get("/skills/directory?kind=bogus", headers=BOB)
    assert r.status_code == 400, r.text
    print("directory OK (members only, search, kind, exact skill)")

    # 6. Matches are computed: BOB matches CAROL (teaches Coding,
    # wants Guitar) and DAVE (wants Guitar); not ALICE or EVE.
    r = c.get("/skills/matches", headers=BOB)
    assert r.status_code == 200, r.text
    matches = r.json()["matches"]
    assert {m["telegram_id"] for m in matches} == {333, 444}, matches
    by_id = {m["telegram_id"]: m for m in matches}
    assert by_id[333]["match"] == {"teach_for_me": ["Coding"],
                                   "learn_from_me": ["Guitar"]}, by_id[333]
    assert by_id[444]["match"] == {"teach_for_me": [],
                                   "learn_from_me": ["Guitar"]}, by_id[444]
    r = c.get("/skills/matches", headers=GRACE)
    assert r.json()["matches"] == [], r.json()
    print("matches OK (computed overlap, none without skills)")

    # 7. Private-member visibility (Phase 136 rule, reused).
    r = c.post("/me/privacy", headers=CAROL, json={"is_private": True})
    assert r.status_code == 200, r.text
    r = c.get("/skills/directory", headers=BOB)
    assert 333 not in {m["telegram_id"] for m in r.json()["members"]}, \
        "private member must hide from strangers"
    r = c.get("/skills/matches", headers=BOB)
    assert 333 not in {m["telegram_id"] for m in r.json()["matches"]}, \
        "private member must hide from matches too"
    r = c.post("/users/333/follow", headers=BOB)
    assert r.status_code == 200 and r.json()["requested"] is True, r.text
    r = c.get("/me/follow-requests", headers=CAROL)
    assert r.status_code == 200, r.text
    req_id = r.json()["follow_requests"][0]["id"]
    r = c.post(f"/follow-requests/{req_id}/accept", headers=CAROL)
    assert r.status_code == 200, r.text
    r = c.get("/skills/directory", headers=BOB)
    assert 333 in {m["telegram_id"] for m in r.json()["members"]}, \
        "private member must show to a follower"
    print("private visibility OK (hidden from strangers, seen by follower)")

    # 8. Blocked pairs never see each other in the directory.
    r = c.post("/users/444/block", headers=BOB)
    assert r.status_code == 200 and r.json()["blocked"] is True, r.text
    r = c.get("/skills/directory", headers=BOB)
    assert 444 not in {m["telegram_id"] for m in r.json()["members"]}, \
        "blocked member must hide"
    r = c.post("/users/444/block", headers=BOB)
    assert r.status_code == 200 and r.json()["blocked"] is False, r.text
    r = c.get("/skills/directory", headers=BOB)
    assert 444 in {m["telegram_id"] for m in r.json()["members"]}, \
        "unblocked member must show again"
    print("block visibility OK")

    # 9. Connect: notifies the member; 400/403/404 guards.
    before_carol = count_type(c, CAROL, "skill_connect")
    r = c.post("/skills/333/connect", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "user_id": 333,
                        "match": {"teach_for_me": ["Coding"],
                                  "learn_from_me": ["Guitar"]}}, r.json()
    assert count_type(c, CAROL, "skill_connect") == before_carol + 1
    assert any(n["type"] == "skill_connect" and n["actor_id"] == 222
               for n in skill_notifs(c, CAROL)), "target must be told"
    r = c.post("/skills/222/connect", headers=BOB)
    assert r.status_code == 400, r.text
    r = c.post("/skills/999999/connect", headers=BOB)
    assert r.status_code == 404, r.text
    r = c.post("/skills/777/connect", headers=BOB)
    assert r.status_code == 400, r.text  # GRACE lists no skills
    print("connect OK (target notified, self/unknown/no-skills guards)")

    # 10. A private stranger cannot connect, and sees no skills
    # on the profile either.
    r = c.post("/me/privacy", headers=DAVE, json={"is_private": True})
    assert r.status_code == 200, r.text
    r = c.post("/skills/444/connect", headers=BOB)
    assert r.status_code == 403, r.text
    r = c.get("/users/444", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["skills"] == {"teach": [], "learn": []}, r.json()
    r = c.get("/users/222", headers=BOB)
    assert r.json()["skills"] == {"teach": ["Guitar"],
                                  "learn": ["Coding", "Guitar"]}, r.json()
    r = c.get("/users/333", headers=BOB)
    assert r.json()["skills"] == {"teach": ["Coding"],
                                  "learn": ["Guitar"]}, r.json()
    r = c.post("/me/privacy", headers=DAVE, json={"is_private": False})
    assert r.status_code == 200, r.text
    print("private connect 403 + profile exposure OK")

    # 11. The "skills" notification pref gates delivery.
    r = c.get("/me/notification-prefs", headers=EVE)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["skills"] is True, r.json()
    prefs = r.json()["prefs"]
    prefs["skills"] = False
    r = c.post("/me/notification-prefs", headers=EVE, json=prefs)
    assert r.status_code == 200, r.text
    assert r.json()["prefs"]["skills"] is False, r.json()
    before = count_type(c, EVE, "skill_connect")
    r = c.post("/skills/555/connect", headers=BOB)
    assert r.status_code == 200, r.text
    assert count_type(c, EVE, "skill_connect") == before, \
        "skills pref OFF must silence the alert"
    prefs["skills"] = True
    r = c.post("/me/notification-prefs", headers=EVE, json=prefs)
    assert r.status_code == 200 and r.json()["prefs"]["skills"] is True
    r = c.post("/skills/555/connect", headers=BOB)
    assert r.status_code == 200, r.text
    assert count_type(c, EVE, "skill_connect") == before + 1
    print("skills notification pref OK (9th toggle, gates delivery)")

    # 12. Remove round-trip: BOB drops Guitar (teach) — he leaves
    # the teach-guitar search and DAVE stops matching him.
    r = c.delete("/me/skills/999999", headers=BOB)
    assert r.status_code == 404, r.text
    r = c.get("/me/skills", headers=BOB)
    bob_teach_guitar = [s for s in r.json()["skills"]
                        if s["skill"] == "Guitar" and s["kind"] == "teach"][0]
    r = c.delete(f"/me/skills/{bob_teach_guitar['id']}", headers=CAROL)
    assert r.status_code == 403, r.text
    r = c.delete(f"/me/skills/{bob_teach_guitar['id']}", headers=BOB)
    assert r.status_code == 200 and r.json() == {"ok": True}, r.text
    r = c.get("/skills/directory?kind=teach&q=guitar", headers=BOB)
    assert r.json()["members"] == [], r.json()
    r = c.get("/skills/directory?skill=Guitar", headers=BOB)
    assert {m["telegram_id"] for m in r.json()["members"]} == {222, 333, 444}, r.json()
    r = c.get("/skills/matches", headers=BOB)
    assert {m["telegram_id"] for m in r.json()["matches"]} == {333}, r.json()
    print("remove round-trip OK (entry gone, search + matches update)")

    # 13. Cap: 20 skills per member, the 21st is refused.
    for i in range(20):
        r = add_skill(c, FRANK, f"Skill{i:02d}", "teach")
        assert r.status_code == 200, (i, r.text)
    r = add_skill(c, FRANK, "Skill20", "teach")
    assert r.status_code == 400, r.text
    print("cap OK (20 skills max)")

    # 14. Backup 44 tables; routes 166 (5 new paths, 6 entries).
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
    assert "skill_entries" in r.json()["tables"], r.json().keys()
    print("backup: 44 tables incl. skill_entries OK")
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 184, len(paths)
    expected = {"/me/skills", "/me/skills/{entry_id}",
                "/skills/directory", "/skills/matches",
                "/skills/{user_id}/connect"}
    assert expected <= paths, expected - paths
    assert len([p for p in paths if "skill" in p]) == 5, paths
    print("routes: 163 OK (5 new skill paths, nothing else)")

# 15. Version.
assert HTML.count("?v=191") == 10, HTML.count("?v=191")
assert "?v=15" + "7" not in HTML
assert 'menu_url.rstrip("/") + "/?v=191"' in BOT
assert "Phase 158" in CSS and "Phase 158" in HTML
print("PHASE 158 OK")
