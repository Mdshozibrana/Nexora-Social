"""Phase-95 tests: Suggested for you in the Feed (owner:
the bot suggests people to follow, in the feed while
scrolling, a little way down).

Server: GET /suggested-users returns members the viewer
does not follow yet \u2014 never self, never already-followed,
never banned, never blocked \u2014 ranked mutual-first
(followed by people you follow), then followers, posts,
points, each with a plain reason. Client: after the 4th
post in the Explore feed (SUGGEST_AFTER_POSTS), a clay
\u201cSuggested for you\u201d card with a sideways-scrolling
row of mini profiles and working Follow buttons; a
short feed gets it at the end; \u2715 hides it for the
session; the Following tab never gets it.
"""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase95.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models

MAIN = open("app/main.py").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
HTML = open("webapp/index.html").read()

# --- static contract ---------------------------------------------
for bit in ('@app.get("/suggested-users")', "mutual_count",
            "Followed by ", "Popular on Nexora",
            "Suggested for you card suggests people to"):
    assert bit in MAIN, bit
for bit in ("SUGGEST_AFTER_POSTS = 4", "suggestCard",
            "loadSuggestedInto", "/suggested-users?limit=10",
            "Suggested for you", "People you may like to follow",
            "suggestDismissed", "suggestInserted",
            'feedPostCount === SUGGEST_AFTER_POSTS',
            '"/users/" + u.telegram_id + "/follow"'):
    assert bit in JS, bit
for bit in (".suggest-card", ".suggest-scroll", ".suggest-person",
            ".suggest-follow", ".suggest-follow.on"):
    assert bit in CSS, bit
assert "app.js?v=100" in HTML and "style.css?v=100" in HTML
print("static contract OK")

def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


VIEWER = H(111, "Viewer")
MID = H(222, "Middleman")
MUTUAL = H(333, "MutualMeg")
POP = H(444, "PopularPam")
F1 = H(555, "FanOne")
F2 = H(666, "FanTwo")
F3 = H(777, "FanThree")
ALREADY = H(888, "AlreadyAnn")
BANNED = H(999, "BannedBen")
BLOCKED = H(1010, "BlockedBob")

with TestClient(app) as c:
    for h in (VIEWER, MID, MUTUAL, POP, F1, F2, F3, ALREADY,
              BANNED, BLOCKED):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200, r.text

    def follow(h, tid):
        r = c.post(f"/users/{tid}/follow", headers=h)
        assert r.status_code == 200, r.text
        return r.json()

    # viewer follows Middleman and AlreadyAnn
    follow(VIEWER, 222)
    follow(VIEWER, 888)
    # Middleman follows MutualMeg -> mutual connection for viewer
    follow(MID, 333)
    # PopularPam gets 3 followers, none of them followed by viewer
    follow(F1, 444)
    follow(F2, 444)
    follow(F3, 444)
    # PopularPam is active: one post
    r = c.post("/posts", headers=POP,
               json={"type": "text", "caption": "hi from pam"})
    assert r.status_code == 200, r.text

    # ban BannedBen directly in the db
    db = SessionLocal()
    try:
        bu = db.get(models.User, 999)
        bu.is_banned = True
        db.commit()
    finally:
        db.close()
    # viewer blocks BlockedBob
    r = c.post("/users/1010/block", headers=VIEWER)
    assert r.status_code == 200, r.text

    r = c.get("/suggested-users", headers=VIEWER)
    assert r.status_code == 200, r.text
    users = r.json()["users"]
    ids = [u["telegram_id"] for u in users]
    # exclusions: self, already-followed (Middleman, AlreadyAnn,
    # and the official account everyone follows), banned, blocked
    for gone in (111, 222, 888, 999, 1010, 1):
        assert gone not in ids, (gone, ids)
    # inclusions
    assert 333 in ids and 444 in ids, ids
    # mutual first, with its reason naming the middleman
    assert users[0]["telegram_id"] == 333, users[0]
    assert users[0]["mutual_count"] == 1, users[0]
    assert users[0]["reason"].startswith("Followed by Middleman"), users[0]
    # popularity data is real
    pam = next(u for u in users if u["telegram_id"] == 444)
    assert pam["followers"] == 3, pam
    assert pam["posts"] == 1, pam
    assert pam["mutual_count"] == 0, pam
    # every suggestion carries the fields the card renders
    for u in users:
        for k in ("first_name", "username", "is_verified",
                  "photo_file_id", "reason"):
            assert k in u, (k, u)
    # limit is honoured and clamped
    r = c.get("/suggested-users?limit=1", headers=VIEWER)
    assert len(r.json()["users"]) == 1, r.text
    # once the viewer follows MutualMeg, she leaves the list
    follow(VIEWER, 333)
    r = c.get("/suggested-users", headers=VIEWER)
    ids2 = [u["telegram_id"] for u in r.json()["users"]]
    assert 333 not in ids2 and 444 in ids2, ids2
    print("suggested-users behaviour OK")

print("PHASE 95 OK")
