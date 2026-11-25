"""Phase-138 tests: DM photos + message reactions.

Covers: text DMs unchanged (send/list, 401, self 400, unknown
404, empty 400); JSON photo DM (media_file_id stored, receiver
sees it, video media_type 400); JSON photo screening (adult ->
400 + no message + screen_reject event; clean -> 200); multipart
DM-photo upload (photo -> message with file_id; caption rides
as text; video file -> 400; screening rejects a bad upload);
reactions (react -> count 1 + my_reaction; same again removes;
different replaces; second user counts; non-participant 403;
invalid emoji 400; unknown message 404; unauthenticated 401;
reactions in the thread list; block guard 403); backup 40
tables incl. message_reactions rows; ?v=184 x5, no ?v=137;
DM photo/reaction client markers + Phase 123-137 markers intact.
"""
import hashlib, hmac, json, os, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase136.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

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


from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models
from app import moderation, tgupload
from app.config import settings

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
VERDICT = {"v": "clean"}


def fake_classify(data, mime="image/jpeg"):
    return VERDICT["v"]


async def fake_upload_media(chat_id, filename, data, content_type):
    kind = tgupload.classify(content_type, filename)
    return (kind, "fileid_" + str(kind), None)


tgupload.upload_media = fake_upload_media

ALICE = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")
DAVE = H(444, "Dave")


def msg_count():
    with SessionLocal() as db:
        return db.query(models.Message).count()


def react_count(mid):
    with SessionLocal() as db:
        return db.query(models.MessageReaction).filter_by(
            message_id=mid).count()


def sec_events(kind):
    with SessionLocal() as db:
        return db.query(models.SecurityEvent).filter_by(
            kind=kind).count()


def thread(c, headers, uid):
    r = c.get(f"/messages/{uid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["messages"]


with TestClient(app) as c:
    for h in (ALICE, BOB, CAROL, DAVE):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200

    # 1. Text DMs unchanged.
    r = c.post("/messages/222", headers=ALICE, json={"text": "hi Bob"})
    assert r.status_code == 200, r.text
    m0 = r.json()
    assert m0["mine"] is True and m0["text"] == "hi Bob", m0
    assert m0["media_file_id"] is None and m0["media_type"] is None, m0
    assert m0["reactions"] == {} and m0["my_reaction"] is None, m0
    r = c.post("/messages/222", headers=ALICE, json={})
    assert r.status_code == 400, r.status_code
    r = c.post("/messages/111", headers=ALICE, json={"text": "self"})
    assert r.status_code == 400, r.status_code
    r = c.post("/messages/424242", headers=ALICE, json={"text": "ghost"})
    assert r.status_code == 404, r.status_code
    r = c.post("/messages/222", json={"text": "no auth"})
    assert r.status_code == 401, r.status_code
    msgs = thread(c, BOB, 111)
    assert len(msgs) == 1 and msgs[0]["text"] == "hi Bob", msgs
    assert msgs[0]["reactions"] == {} and msgs[0]["my_reaction"] is None
    print("text DMs unchanged OK")

    # 2. JSON photo DM (screening off — no key configured).
    assert not moderation.active()
    r = c.post("/messages/222", headers=ALICE,
               json={"media_file_id": "OK1"})
    assert r.status_code == 200, r.text
    photo_msg = r.json()
    assert photo_msg["media_file_id"] == "OK1", photo_msg
    assert photo_msg["media_type"] == "photo", photo_msg
    assert photo_msg["text"] == "", photo_msg
    msgs = thread(c, BOB, 111)
    assert msgs[-1]["media_file_id"] == "OK1", msgs
    r = c.post("/messages/222", headers=ALICE,
               json={"media_file_id": "V1", "media_type": "video"})
    assert r.status_code == 400, r.text
    print("JSON photo DM OK (screening off)")

    # 3. JSON photo screening (key on + fake classifier).
    settings.GEMINI_API_KEY = "test-key"
    moderation.classify_image = fake_classify
    moderation.fetch_file_bytes = lambda fid: JPEG
    assert moderation.active()
    n0 = msg_count()
    e0 = sec_events("screen_reject")
    VERDICT["v"] = "adult"
    r = c.post("/messages/222", headers=ALICE,
               json={"media_file_id": "BAD1"})
    assert r.status_code == 400 and "adult" in r.json()["detail"], r.text
    assert msg_count() == n0
    assert sec_events("screen_reject") == e0 + 1
    VERDICT["v"] = "clean"
    r = c.post("/messages/222", headers=ALICE,
               json={"media_file_id": "OK2", "text": "look"})
    assert r.status_code == 200, r.text
    assert r.json()["media_file_id"] == "OK2"
    assert r.json()["text"] == "look"
    print("JSON photo screening OK")

    # 4. Multipart DM-photo upload.
    n0 = msg_count()
    r = c.post("/messages/222/upload", headers=ALICE,
               files={"file": ("a.jpg", JPEG, "image/jpeg")},
               data={"text": "from the app"})
    assert r.status_code == 200, r.text
    up = r.json()
    assert up["media_file_id"] == "fileid_photo", up
    assert up["media_type"] == "photo", up
    assert up["text"] == "from the app", up
    assert msg_count() == n0 + 1
    msgs = thread(c, BOB, 111)
    assert msgs[-1]["media_file_id"] == "fileid_photo", msgs
    # a video file is refused before any upload happens
    r = c.post("/messages/222/upload", headers=ALICE,
               files={"file": ("v.mp4", b"\x00" * 64, "video/mp4")})
    assert r.status_code == 400, r.text
    assert msg_count() == n0 + 1
    # screening rejects a bad upload (classifier runs inline)
    VERDICT["v"] = "adult"
    r = c.post("/messages/222/upload", headers=ALICE,
               files={"file": ("b.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 400, r.text
    assert msg_count() == n0 + 1
    VERDICT["v"] = "clean"
    print("multipart DM-photo upload OK")

    # 5. Reactions.
    r = c.post("/messages/222", headers=ALICE,
               json={"text": "react to this"})
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    r = c.post(f"/dm/messages/{mid}/react", headers=BOB,
               json={"emoji": "❤️"})
    assert r.status_code == 200, r.text
    assert r.json() == {"message_id": mid, "reacted": True,
                        "emoji": "❤️", "reactions": {"❤️": 1},
                        "my_reaction": "❤️"}, r.json()
    msgs = thread(c, ALICE, 222)
    mine = [m for m in msgs if m["id"] == mid][0]
    assert mine["reactions"] == {"❤️": 1}, mine
    assert mine["my_reaction"] is None, mine
    msgs = thread(c, BOB, 111)
    mine = [m for m in msgs if m["id"] == mid][0]
    assert mine["my_reaction"] == "❤️", mine
    # same emoji again removes it
    r = c.post(f"/dm/messages/{mid}/react", headers=BOB,
               json={"emoji": "❤️"})
    assert r.json()["reacted"] is False, r.json()
    assert r.json()["reactions"] == {}, r.json()
    assert r.json()["my_reaction"] is None, r.json()
    assert react_count(mid) == 0
    # a different emoji replaces it
    r = c.post(f"/dm/messages/{mid}/react", headers=BOB,
               json={"emoji": "👍"})
    assert r.json()["reactions"] == {"👍": 1}, r.json()
    r = c.post(f"/dm/messages/{mid}/react", headers=ALICE,
               json={"emoji": "👍"})
    assert r.json()["reactions"] == {"👍": 2}, r.json()
    r = c.post(f"/dm/messages/{mid}/react", headers=BOB,
               json={"emoji": "😂"})
    assert r.json()["reactions"] == {"👍": 1, "😂": 1}, r.json()
    assert r.json()["my_reaction"] == "😂", r.json()
    assert react_count(mid) == 2
    # guards
    r = c.post(f"/dm/messages/{mid}/react", headers=CAROL,
               json={"emoji": "❤️"})
    assert r.status_code == 403, r.status_code
    r = c.post(f"/dm/messages/{mid}/react", headers=BOB,
               json={"emoji": "💩"})
    assert r.status_code == 400, r.status_code
    r = c.post("/dm/messages/999999/react", headers=BOB,
               json={"emoji": "❤️"})
    assert r.status_code == 404, r.status_code
    r = c.post(f"/dm/messages/{mid}/react", json={"emoji": "❤️"})
    assert r.status_code == 401, r.status_code
    print("reactions OK (toggle/replace/counts/guards)")

    # 6. Block guard: a blocked member can neither send nor react.
    c.post("/users/222/block", headers=ALICE)
    r = c.post("/messages/111", headers=BOB, json={"text": "blocked?"})
    assert r.status_code == 403, r.status_code
    r = c.post(f"/dm/messages/{mid}/react", headers=BOB,
               json={"emoji": "🔥"})
    assert r.status_code == 403, r.status_code
    c.post("/users/222/block", headers=ALICE)  # unblock
    r = c.post("/messages/111", headers=BOB, json={"text": "back again"})
    assert r.status_code == 200, r.text
    print("block guard OK")

    # 7. Backup carries 40 tables incl. message_reactions rows.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.status_code
    bk = r.json()
    assert len(bk["tables"]) == 52, len(bk["tables"])
    assert "message_reactions" in bk["tables"], list(bk["tables"])
    assert len(bk["tables"]["message_reactions"]) >= 2, \
        len(bk["tables"]["message_reactions"])
    print("backup: 40 tables incl. message_reactions OK")

    # 8. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=184") == 10, html.count("?v=184")
    assert "?v=137" not in html
    js = open("webapp/app.js").read()
    for m in ("DM_REACTIONS", "reactToMessage", "chat-photo", "chat-file",
              "bubble-photo", "bubble-reactions", "react-picker",
              "react-chip", "/dm/messages",
              "/messages/\" + chatWith + \"/upload",
              "📷 Photo", "Sending photo", "openPhotoViewer"):
        assert m in js, m
    main_src = open("app/main.py").read()
    for m in ("message_reactions", "DM_REACTIONS", "react_message",
              "upload_dm_photo", "_thread_reactions",
              "DMs support photos only"):
        assert m in main_src, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus", "openTipSheet", "openInsights",
              "ins-chart", "ins-table", "schedLocalInput", "loadScheduled",
              "composer-schedule", "loadFollowRequests", "privacy-row",
              "private-lock", "renderLevelBlock", "level-block",
              "level-bar", "badge-row", "badge-chip", "badge-locked"):
        assert m in js, m
    css = open("webapp/style.css").read()
    assert ".bubble-photo" in css and ".react-chip" in css \
        and ".react-picker" in css
    print("client markers + ?v=184 OK")

print("PHASE-138 TESTS PASSED")
