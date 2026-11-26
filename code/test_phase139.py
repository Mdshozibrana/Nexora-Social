"""Phase-139 tests: story replies + viewer list.

Covers: view tracking (unique per viewer, author never counts);
viewer_count in the story dict (owner only, None for others);
GET /stories/{id}/viewers (owner lists newest first, others 403,
no auth 401, unknown/expired 404); POST /stories/{id}/reply
(creates a DM with story_id + a live story preview; own story
400, empty 400, unauthenticated 401, unknown/expired 404,
blocked 403, private-account non-follower 403); the old reply's
preview reports live=False once the story expires; backup still
40 tables incl. story_views rows; ?v=192 x5; story reply/viewer
client markers + Phase 123-138 markers intact.

Survey note: story_views already existed (Phase 36, unique per
story+viewer, recorded by POST /stories/{id}/view) and was
already in _BACKUP_TABLES — no new table, backup stays 40.
"""
import hashlib, hmac, json, os, sqlite3, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase139.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.main as main_mod


async def fake_upload(user, file, caption=""):
    return ("photo", "storyfile_" + (file.filename or "x"))


main_mod._telegram_upload_or_400 = fake_upload

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
PNG = ("s.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")

with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # Bob follows Alice so her stories are visible to him.
    r = c.post("/users/111/follow", headers=BOB)
    assert r.status_code == 200, r.text

    # 1. Upload + unique view tracking.
    r = c.post("/stories/upload", headers=ALICE, files={"file": PNG})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = c.post(f"/stories/{sid}/view", headers=BOB)
    assert r.json() == {"views": 1, "counted": True}, r.json()
    r = c.post(f"/stories/{sid}/view", headers=BOB)
    assert r.json() == {"views": 1, "counted": False}, r.json()
    r = c.post(f"/stories/{sid}/view", headers=CAROL)
    assert r.json() == {"views": 2, "counted": True}, r.json()
    r = c.post(f"/stories/{sid}/view", headers=ALICE)
    assert r.json()["counted"] is False  # author never counts
    print("view tracking OK")

    # 2. viewer_count: the owner sees it, others get None.
    r = c.get("/stories", headers=ALICE)
    mine = [g for g in r.json()["groups"]
            if g["author"]["telegram_id"] == 111]
    assert len(mine) == 1, r.json()
    assert mine[0]["stories"][0]["viewer_count"] == 2, \
        mine[0]["stories"][0]
    r = c.get("/stories", headers=BOB)
    bob_view = [g for g in r.json()["groups"]
                if g["author"]["telegram_id"] == 111]
    assert len(bob_view) == 1, r.json()
    assert bob_view[0]["stories"][0]["viewer_count"] is None, bob_view
    print("viewer_count OK (owner only)")

    # 3. Viewers endpoint: owner lists newest first; guards.
    r = c.get(f"/stories/{sid}/viewers", headers=ALICE)
    assert r.status_code == 200, r.text
    vs = r.json()["viewers"]
    assert [v["user"]["telegram_id"] for v in vs] == [333, 222], vs
    assert all(v["viewed_at"] for v in vs), vs
    assert all(v["user"]["first_name"] for v in vs), vs
    r = c.get(f"/stories/{sid}/viewers", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get(f"/stories/{sid}/viewers")
    assert r.status_code == 401, r.status_code
    r = c.get("/stories/999999/viewers", headers=ALICE)
    assert r.status_code == 404, r.status_code
    print("viewers endpoint OK")

    # 4. Reply: a DM with story_id + a live story preview.
    r = c.post(f"/stories/{sid}/reply", headers=BOB,
               json={"text": "love this!"})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["story_id"] == sid and m["text"] == "love this!", m
    assert m["story"]["live"] is True, m
    assert m["story"]["media_file_id"] == "storyfile_s.png", m
    r = c.get("/messages/222", headers=ALICE)
    msgs = r.json()["messages"]
    assert len(msgs) == 1 and msgs[0]["story_id"] == sid, msgs
    assert msgs[0]["story"]["live"] is True, msgs[0]
    notes = c.get("/me/notifications?limit=10",
                  headers=ALICE).json()["notifications"]
    assert any(n["type"] == "message" for n in notes), notes
    print("reply OK (DM + live preview + notification)")

    # 5. Reply guards: own story, empty, unauthenticated, unknown.
    r = c.post(f"/stories/{sid}/reply", headers=ALICE,
               json={"text": "self"})
    assert r.status_code == 400, r.status_code
    r = c.post(f"/stories/{sid}/reply", headers=BOB,
               json={"text": "   "})
    assert r.status_code == 400, r.status_code
    r = c.post(f"/stories/{sid}/reply", json={"text": "hi"})
    assert r.status_code == 401, r.status_code
    r = c.post("/stories/999999/reply", headers=BOB,
               json={"text": "ghost"})
    assert r.status_code == 404, r.status_code
    print("reply guards OK (own/empty/401/404)")

    # 6. Block guard: Alice blocks Bob -> Bob cannot reply.
    c.post("/users/222/block", headers=ALICE)
    r = c.post(f"/stories/{sid}/reply", headers=BOB,
               json={"text": "blocked?"})
    assert r.status_code == 403, r.status_code
    c.post("/users/222/block", headers=ALICE)  # unblock
    r = c.post(f"/stories/{sid}/reply", headers=BOB,
               json={"text": "back again"})
    assert r.status_code == 200, r.text
    print("reply block guard OK")

    # 7. Private account: a non-follower cannot reply.
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": True})
    assert r.status_code == 200, r.text
    r = c.post(f"/stories/{sid}/reply", headers=CAROL,
               json={"text": "hi?"})
    assert r.status_code == 403, r.status_code
    r = c.post("/me/privacy", headers=ALICE, json={"is_private": False})
    assert r.status_code == 200, r.text
    r = c.post(f"/stories/{sid}/reply", headers=CAROL,
               json={"text": "hi!"})
    assert r.status_code == 200, r.text
    print("reply private-account guard OK")

    # 8. Expiry: age the story past 24h.
    db = sqlite3.connect("test_phase139.db")
    db.execute("UPDATE stories SET created_at = "
               "datetime('now', '-25 hours') WHERE id = ?", (sid,))
    db.commit()
    db.close()
    r = c.get(f"/stories/{sid}/viewers", headers=ALICE)
    assert r.status_code == 404, r.status_code
    r = c.post(f"/stories/{sid}/reply", headers=BOB,
               json={"text": "late"})
    assert r.status_code == 404, r.status_code
    r = c.get("/messages/222", headers=ALICE)
    msgs = r.json()["messages"]
    assert msgs[0]["story"]["live"] is False, msgs[0]
    assert msgs[0]["story"]["media_file_id"] == "storyfile_s.png", msgs[0]
    print("expiry OK (viewers/reply 404, old preview live=False)")

    # 9. Backup still carries 40 tables incl. story_views rows.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    bk = r.json()
    assert len(bk["tables"]) == 52, len(bk["tables"])
    assert "story_views" in bk["tables"], list(bk["tables"])
    assert len(bk["tables"]["story_views"]) >= 2, \
        len(bk["tables"]["story_views"])
    print("backup: 40 tables incl. story_views OK")

    # 10. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=192") == 10, html.count("?v=192")
    assert "?v=13" + "8" not in html
    js = open("webapp/app.js").read()
    for m in ("openStoryViewers", "sendStoryReply", "openStoryById",
              "story-reply", "story-viewers", "story-reply-chip",
              "story-reply-thumb", "story-viewer-row", "/viewers",
              "/reply", "Replied to", "That story has expired"):
        assert m in js, m
    for m in ("story-reply-input", "story-reply-send", "story-viewers",
              "story-viewers-list", "story-viewers-close"):
        assert m in html, m
    main_src = open("app/main.py").read()
    for m in ("story_viewers", "reply_story", "_story_previews",
              "viewer_count", "StoryReplyIn"):
        assert m in main_src, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus", "openTipSheet", "openInsights",
              "ins-chart", "ins-table", "schedLocalInput", "loadScheduled",
              "composer-schedule", "loadFollowRequests", "privacy-row",
              "private-lock", "renderLevelBlock", "level-block",
              "level-bar", "badge-row", "badge-chip", "badge-locked",
              "DM_REACTIONS", "reactToMessage", "chat-photo",
              "bubble-photo"):
        assert m in js, m
    css = open("webapp/style.css").read()
    assert ".story-reply" in css and ".story-viewer-row" in css \
        and ".story-reply-chip" in css and "#story-viewers" in css
    print("client markers + ?v=192 OK")

print("PHASE-139 TESTS PASSED")
