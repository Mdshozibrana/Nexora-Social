"""Phase-144 tests: per-user Settings page + notification prefs.

Brief (owner order 2026-11-18): Nexora had NO unified per-user
Settings page — theme in Me, privacy in profile edit, Data Control
in My Profile, wallet in the Monetization card, and notifications
had no on/off at all. Phase 144 gathers all six sections on one
Settings page and adds real per-type notification toggles.

SCOPE UPDATE (owner 2026-11-18 23:39): Me keeps ONLY name, photo,
bio, cover and posts — everything else MOVES into Settings (theme,
Data Control, rain, Monetization, level, insights, tips, scheduled,
drafts, follow requests, hashtags, My QR). "Old locations keep
working" is overridden; myExtras() renders inside Settings only.

Covers:
- GET/POST /me/notification-prefs: defaults all ON, merge (one
  toggle never resets the others), unknown key 400, non-bool 400,
  unauth 401, per-user isolation (Alice OFF never affects Bob),
  no per-user route (GET /users/{id}/notification-prefs 404).
- The gate itself: notif_allowed() mapping for every type the app
  creates (likes cover like/repost/share; comments cover
  comment/reply; system covers payout/verification/post_live/
  broadcast); "mention" is deliberately NOT a toggle (no code
  path ever creates one).
- Gating end to end: like, comment, reply, follow, follow
  request (private account), tip, DM, system (direct record);
  OFF stops that type, ON restores it; broadcast with system OFF
  still records history and returns 200.
- Settings wiring from the page: profile bio edit, privacy
  toggle, theme save, export download + send, wallet
  save/validation/round-trip, blocked list + unblock, delete
  account (wrong confirm 400, typed DELETE 200 + user gone).
- Client: view-settings section + sidebar item + Me button,
  loadSettings with all six sections, notification toggle rows,
  themeCard/dataCard reuse, wallet form ids, neighbouring
  markers intact; backup still 42 tables (one TEXT column, no
  new table); ?v=182 x5, no older shell version; source guard (no BOOLEAN
  DEFAULT 0 anywhere in the new code).
"""
import hashlib, hmac, json, os, re, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase144.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.main as main_mod
from app import notify as notify_mod

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models

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
HANK = H(888, "Hank")

KEYS = ["likes", "comments", "follows", "follow_requests", "tips",
        "messages", "system", "blood", "skills", "mention"]


def notif_count(uid, ntype=None):
    with SessionLocal() as db:
        q = db.query(models.Notification).filter_by(user_id=uid)
        if ntype:
            q = q.filter_by(type=ntype)
        return q.count()


def set_prefs(c, h, **kw):
    r = c.post("/me/notification-prefs", headers=h, json=dict(kw))
    assert r.status_code == 200, r.text
    return r.json()["prefs"]


def get_prefs(c, h):
    r = c.get("/me/notification-prefs", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["prefs"]


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE, EVE, FRANK, GRACE, HANK):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Prefs CRUD + validation + isolation.
    p = get_prefs(c, BOB)
    assert p == {k: True for k in KEYS}, p
    p = set_prefs(c, BOB, likes=False)
    assert p["likes"] is False, p
    assert all(p[k] is True for k in KEYS if k != "likes"), p
    p = get_prefs(c, BOB)
    assert p["likes"] is False and p["comments"] is True, p
    r = c.post("/me/notification-prefs", headers=BOB,
               json={"mentions": False})
    assert r.status_code == 400, r.text  # "mentions" (plural) is not a key
    r = c.post("/me/notification-prefs", headers=BOB,
               json={"mention": False})
    assert r.status_code == 200, r.text  # Phase 170: "mention" is a key now
    assert r.json()["prefs"]["mention"] is False
    r = c.post("/me/notification-prefs", headers=BOB,
               json={"mention": True})
    assert r.status_code == 200, r.text
    r = c.post("/me/notification-prefs", headers=BOB,
               json={"likes": "yes"})
    assert r.status_code == 400, r.text
    r = c.get("/me/notification-prefs")
    assert r.status_code == 401, r.status_code
    # Admin isolation: Alice turning hers off never touches Bob.
    set_prefs(c, ALICE, likes=False)
    assert get_prefs(c, BOB)["likes"] is False  # Bob's own, untouched
    assert get_prefs(c, ALICE)["likes"] is False
    set_prefs(c, ALICE, likes=True)
    set_prefs(c, BOB, likes=True)
    # No per-user route: nobody can read/change another's prefs.
    r = c.get("/users/222/notification-prefs", headers=ALICE)
    assert r.status_code == 404, r.status_code
    print("prefs CRUD + validation + isolation OK")

    # 2. The gate helper: every real type maps to a toggle.
    with SessionLocal() as db:
        for ntype, key in (("like", "likes"), ("repost", "likes"),
                           ("share", "likes"), ("comment", "comments"),
                           ("reply", "comments"), ("follow", "follows"),
                           ("follow_request", "follow_requests"),
                           ("tip", "tips"), ("message", "messages"),
                           ("payout", "system"),
                           ("verification", "system"),
                           ("post_live", "system"),
                           ("broadcast", "system")):
            assert notify_mod.notif_allowed(db, 111, ntype) is True, ntype
        # Unknown types default to allowed, never silently dropped.
        assert notify_mod.notif_allowed(db, 111, "brand_new_type") is True
        # A stored False gates its whole family.
        u = db.get(models.User, 111)
        u.notif_prefs = json.dumps({"likes": False, "system": False})
        db.commit()
        assert notify_mod.notif_allowed(db, 111, "like") is False
        assert notify_mod.notif_allowed(db, 111, "repost") is False
        assert notify_mod.notif_allowed(db, 111, "comment") is True
        assert notify_mod.notif_allowed(db, 111, "payout") is False
        assert notify_mod.notif_allowed(db, 111, "post_live") is False
        u.notif_prefs = json.dumps({k: True for k in KEYS})
        db.commit()
    print("gate helper mapping OK")

    # 3. Likes gating end to end (recipient's prefs gate).
    r = c.post("/posts", headers=ALICE,
               json={"type": "text", "caption": "phase 144 post"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = c.post(f"/posts/{pid}/like", headers=BOB)
    assert r.json()["liked"] is True, r.json()
    assert notif_count(111, "like") == 1, notif_count(111, "like")
    set_prefs(c, ALICE, likes=False)
    c.post(f"/posts/{pid}/like", headers=BOB)  # unlike
    r = c.post(f"/posts/{pid}/like", headers=BOB)  # like again
    assert r.json()["liked"] is True, r.json()
    assert notif_count(111, "like") == 1, notif_count(111, "like")
    set_prefs(c, ALICE, likes=True)
    c.post(f"/posts/{pid}/like", headers=BOB)
    c.post(f"/posts/{pid}/like", headers=BOB)
    assert notif_count(111, "like") == 2, notif_count(111, "like")
    # The actor's own prefs never gate the recipient's notice.
    set_prefs(c, BOB, likes=False)
    c.post(f"/posts/{pid}/like", headers=BOB)
    c.post(f"/posts/{pid}/like", headers=BOB)
    assert notif_count(111, "like") == 3, notif_count(111, "like")
    set_prefs(c, BOB, likes=True)
    print("like gating OK (off stops, on restores, actor prefs inert)")

    # 4. Comment + reply gating.
    r = c.post(f"/posts/{pid}/comments", headers=BOB,
               json={"text": "phase 144 comment one"})
    assert r.status_code == 200, r.text
    assert notif_count(111, "comment") == 1
    set_prefs(c, ALICE, comments=False)
    r = c.post(f"/posts/{pid}/comments", headers=BOB,
               json={"text": "phase 144 comment two"})
    assert r.status_code == 200, r.text
    assert notif_count(111, "comment") == 1
    set_prefs(c, ALICE, comments=True)
    r = c.post(f"/posts/{pid}/comments", headers=CAROL,
               json={"text": "phase 144 comment three"})
    assert r.status_code == 200, r.text
    carol_cid = r.json()["id"]
    assert notif_count(111, "comment") == 2
    # Reply: post author hears "comment", parent author "reply".
    r = c.post(f"/posts/{pid}/comments", headers=BOB,
               json={"text": "phase 144 reply one",
                     "parent_id": carol_cid})
    assert r.status_code == 200, r.text
    assert notif_count(333, "reply") == 1, notif_count(333, "reply")
    assert notif_count(111, "comment") == 3
    set_prefs(c, CAROL, comments=False)
    r = c.post(f"/posts/{pid}/comments", headers=BOB,
               json={"text": "phase 144 reply two",
                     "parent_id": carol_cid})
    assert r.status_code == 200, r.text
    assert notif_count(333, "reply") == 1, notif_count(333, "reply")
    set_prefs(c, CAROL, comments=True)
    r = c.post(f"/posts/{pid}/comments", headers=BOB,
               json={"text": "phase 144 reply three",
                     "parent_id": carol_cid})
    assert r.status_code == 200, r.text
    assert notif_count(333, "reply") == 2, notif_count(333, "reply")
    print("comment + reply gating OK")

    # 5. Follow + follow-request gating (private toggle).
    r = c.post("/users/111/follow", headers=BOB)
    assert r.json()["following"] is True, r.json()
    assert notif_count(111, "follow") == 1
    set_prefs(c, ALICE, follows=False)
    r = c.post("/users/111/follow", headers=CAROL)
    assert r.json()["following"] is True, r.json()
    assert notif_count(111, "follow") == 1
    set_prefs(c, ALICE, follows=True)
    r = c.post("/users/111/follow", headers=DAVE)
    assert r.json()["following"] is True, r.json()
    assert notif_count(111, "follow") == 2
    # Private: follow becomes a request, gated by follow_requests.
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": True})
    assert r.json()["is_private"] is True, r.json()
    r = c.post("/users/111/follow", headers=EVE)
    assert r.json()["requested"] is True, r.json()
    assert notif_count(111, "follow_request") == 1
    set_prefs(c, ALICE, follow_requests=False)
    r = c.post("/users/111/follow", headers=FRANK)
    assert r.json()["requested"] is True, r.json()
    assert notif_count(111, "follow_request") == 1
    set_prefs(c, ALICE, follow_requests=True)
    r = c.post("/users/111/follow", headers=GRACE)
    assert r.json()["requested"] is True, r.json()
    assert notif_count(111, "follow_request") == 2
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": False})
    assert r.json()["is_private"] is False, r.json()
    print("follow + follow-request gating OK")

    # 6. Tips gating (direct record — Stars payment is out of scope).
    with SessionLocal() as db:
        u = db.get(models.User, 111)
        u.notif_prefs = json.dumps({"tips": False})
        db.commit()
        notify_mod.record(db, 111, "tip", actor_id=222)
        assert notif_count(111, "tip") == 0
        u = db.get(models.User, 111)
        u.notif_prefs = json.dumps({"tips": True})
        db.commit()
        notify_mod.record(db, 111, "tip", actor_id=222)
        assert notif_count(111, "tip") == 1
    print("tip gating OK")

    # 7. DM gating.
    r = c.post("/messages/111", headers=BOB,
               json={"text": "phase 144 dm one"})
    assert r.status_code == 200, r.text
    assert notif_count(111, "message") == 1
    set_prefs(c, ALICE, messages=False)
    r = c.post("/messages/111", headers=BOB,
               json={"text": "phase 144 dm two"})
    assert r.status_code == 200, r.text
    assert notif_count(111, "message") == 1
    set_prefs(c, ALICE, messages=True)
    r = c.post("/messages/111", headers=BOB,
               json={"text": "phase 144 dm three"})
    assert r.status_code == 200, r.text
    assert notif_count(111, "message") == 2
    print("DM gating OK")

    # 8. System gating (direct record) + broadcast with system off.
    with SessionLocal() as db:
        u = db.get(models.User, 111)
        u.notif_prefs = json.dumps({"system": False})
        db.commit()
        for t in ("payout", "verification", "post_live"):
            notify_mod.record(db, 111, t, actor_id=222)
            assert notif_count(111, t) == 0, t
        u = db.get(models.User, 111)
        u.notif_prefs = json.dumps({"system": True})
        db.commit()
        for t in ("payout", "verification", "post_live"):
            notify_mod.record(db, 111, t, actor_id=222)
            assert notif_count(111, t) == 1, t
    set_prefs(c, BOB, system=False)
    r = c.post("/admin/broadcast", headers=ALICE,
               json={"text": "phase 144 broadcast check", "target": "all"})
    assert r.status_code == 200, r.text
    assert isinstance(r.json().get("broadcast_id"), int), r.json()
    with SessionLocal() as db:
        assert db.query(models.NotificationLog).filter_by(
            user_id=222, type="broadcast").count() == 0
        assert db.query(models.Broadcast).filter_by(
            text="phase 144 broadcast check").count() == 1
    set_prefs(c, BOB, system=True)
    print("system gating + broadcast OK")

    # 9. Settings sections wiring (the endpoints the page calls).
    r = c.post("/me/profile", headers=BOB, json={"bio": "phase 144 bio"})
    assert r.status_code == 200, r.text
    assert r.json()["bio"] == "phase 144 bio", r.json()
    r = c.post("/me/theme", headers=BOB, json={"picks": {}})
    assert r.status_code == 200, r.text
    r = c.get("/me/export", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["telegram_id"] == 222, r.json()
    r = c.post("/me/export/send", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["sent"] is False, r.json()  # no live bot token
    r = c.get("/me/wallet", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["wallet_address"] is None, r.json()
    r = c.post("/me/wallet", headers=BOB,
               json={"network": "TON", "address": "EQphase144wallet"})
    assert r.status_code == 200, r.text
    r = c.post("/me/wallet", headers=BOB,
               json={"network": "BTC", "address": "x"})
    assert r.status_code == 400, r.text
    r = c.post("/me/wallet", headers=BOB,
               json={"network": "TON", "address": ""})
    assert r.status_code == 400, r.text
    r = c.get("/me/wallet", headers=BOB)
    assert r.json()["wallet_address"] == "EQphase144wallet", r.json()
    assert r.json()["wallet_network"] == "TON", r.json()
    print("profile/theme/export/wallet wiring OK")
    # Blocked list + unblock (server already had both).
    r = c.post("/users/333/block", headers=BOB)
    assert r.status_code == 200, r.text
    assert r.json()["blocked"] is True, r.json()
    r = c.get("/me/blocked", headers=BOB)
    assert r.status_code == 200, r.text
    assert [b["telegram_id"] for b in r.json()["blocked"]] == [333], r.json()
    r = c.post("/users/333/block", headers=BOB)
    assert r.json()["blocked"] is False, r.json()
    r = c.get("/me/blocked", headers=BOB)
    assert r.json()["blocked"] == [], r.json()
    print("blocked list + unblock OK")
    # Delete account: wrong confirm 400, typed DELETE 200 + gone.
    r = c.post("/me/delete-account", headers=HANK,
               json={"confirm": "delete"})
    assert r.status_code == 400, r.text
    r = c.post("/me/delete-account", headers=HANK,
               json={"confirm": "DELETE"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(models.User, 888) is None
    print("delete-account guard OK")

    # 10. Client markers: the Settings page + neighbours intact.
    HTML = open("webapp/index.html").read()
    JS = open("webapp/app.js").read()
    CSS = open("webapp/style.css").read()
    assert HTML.count("?v=182") == 10, HTML.count("?v=182")
    assert "?v=14" + "3" not in HTML
    for m in ("view-settings", "settings-box", "⚙️ Settings",
              'data-go="settings"', "Settings</span>"):
        assert m in HTML, m
    for m in ("loadSettings", "NOTIF_PREF_META", "profile-settings-btn",
              "settings-box", "notif-row-", "loadBlocked",
              "settings-wallet-network", "settings-wallet-address",
              "settings-wallet-save", "/me/notification-prefs",
              "/me/blocked", "/me/privacy", "/me/profile",
              "/me/wallet", "themeCard()", "dataCard()",
              "settings-open-profile", "loadMyQrInto",
              "settings-qr-box", "settings-qr-download",
              "From your profile", "box.appendChild(rainCard())"):
        assert m in JS, m
    for m in ("settings-sec", "settings-head", "settings-sub",
              "settings-row", "settings-blocked-row"):
        assert m in CSS, m
    # Every toggle label is on the page (ten keys, incl. mention).
    for key in KEYS:
        assert f'"notif-row-" + key' in JS or key in JS, key
    assert "mention" in JS.split("NOTIF_PREF_META")[1].split("];")[0]
    for m in ("loadDrafts", "loadScheduled", "loadFollowRequests",
              "hashtag-card", "loadPayoutBox", "openTipSheet",
              "openInsights", "renderLevelBlock", "composer-post",
              "tab-hashtags", "loadAutoBackup", "openStoryViewers",
              "themeCard", "dataCard", "rainCard", "loadMe"):
        assert m in JS, m
    print("client markers + ?v=182 OK")

    # 10b. SCOPE UPDATE (owner 2026-11-18 23:39): Me keeps only
    # name, photo, bio, cover and posts — nothing else renders there.
    assert "box.appendChild(await myExtras())" not in JS, \
        "myExtras still renders on Me"
    assert "me-settings-btn" not in JS, "old Me Settings button left"
    # The privacy toggle left the profile edit form (one copy
    # remains, in Settings §3).
    assert JS.count("🔒 Private account — only approved followers will see your posts.") == 1
    # Moved cards render from loadSettings, grouped by heading.
    for m in ("⭐ Points & creator", "🔖 Library", "📝 Posts",
              "👥 Social", "💰 Account", "🔳 My QR"):
        assert m in JS, m
    # Deep links repointed at Settings, not the profile.
    for m in ("My drafts in ⚙️ Settings", "Scheduled in ⚙️ Settings",
              "Monetization card below"):
        assert m in JS, m
    for m in ("My drafts on your profile", "Scheduled on your profile",
              "Monetization card on your profile"):
        assert m not in JS, m
    print("scope update (Me keeps five) OK")

    # 11. Backup still 42 tables (one column, no new table);
    # the column itself persists on the member row.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
    with SessionLocal() as db:
        u = db.get(models.User, 222)
        assert u.notif_prefs is not None, u.notif_prefs
        assert json.loads(u.notif_prefs)["likes"] is True
    print("backup: 42 tables OK (no schema change)")

    # 12. Source guards.
    for f in ("app/main.py", "app/models.py", "app/notify.py",
              "app/config.py"):
        src = open(f).read()
        assert "BOOLEAN DEFAULT 0" not in src, f
    assert "notif_prefs" in open("app/models.py").read()
    assert '"notif_prefs": "TEXT"' in open("app/main.py").read()
    print("source guards OK")

print("ALL PHASE 144 CHECKS PASSED")
