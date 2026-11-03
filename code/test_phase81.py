"""Phase-81 tests: AI media screening (owner's rule — adult or
graphic media must never become a post).

Contract: while a Gemini key is configured, photos and videos
are classified BEFORE posting on every route: Mini App upload
(photo inline, video in its background job), the JSON post
endpoint (file_id fetched and screened), and the bot-chat route.
Verdicts other than "clean" create NO post and tell the member
why. With no key configured, screening is off and posting works
exactly as before. Designs (admin-only) skip screening.
"""
import asyncio, hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase81.db"
os.environ["ADMIN_IDS"] = "777"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import notify

SENT = []

async def fake_send(chat_id, text):
    SENT.append((chat_id, text))
    return True

notify.send_message = fake_send

import app.main as main_mod
from app import moderation, tgupload, videoutil
from app.config import settings
from app.db import SessionLocal
from app import models

async def fake_upload_media(chat_id, filename, data, content_type):
    kind = tgupload.classify(content_type, filename)
    return (kind, "fileid_" + str(kind), None)

tgupload.upload_media = fake_upload_media


def fake_transcode(src, dst):
    with open(src, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data)

videoutil.transcode_to_mp4 = fake_transcode

from fastapi.testclient import TestClient
from app.main import app

def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())), "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)

def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid,
                                            "first_name": name})}


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
VERDICT = {"v": "clean"}


def fake_classify(data, mime="image/jpeg"):
    return VERDICT["v"]


def post_count():
    db = SessionLocal()
    try:
        return db.query(models.Post).count()
    finally:
        db.close()


# --- 1. reply parsing ------------------------------------------------
assert moderation._verdict_from_reply(
    '{"adult": true, "gore": false}') == "adult"
assert moderation._verdict_from_reply(
    '{"adult": false, "gore": true}') == "gore"
assert moderation._verdict_from_reply(
    '{"adult": false, "gore": false}') == "clean"
assert moderation._verdict_from_reply(
    'Sure: {"adult": true, "gore": true} done') == "gore"
assert moderation._verdict_from_reply("no json here") is None
assert moderation._verdict_from_reply("") is None
assert moderation.block_message("photo", "adult").startswith("🚫")
assert "graphic" in moderation.block_message("video", "gore")
print("parsing OK")

with TestClient(app) as c:
    # warm-up: creates the member and triggers the one-time
    # welcome-post seeding, so the counts below are stable
    r = c.post("/posts", headers=H(555, "Member"),
               json={"type": "text", "caption": "warm up"})
    assert r.status_code == 200, r.text

    # --- 2. no key configured: screening off, upload works --------
    assert not moderation.active()
    n0 = post_count()
    r = c.post("/posts/upload", headers=H(555, "Member"),
               files={"file": ("a.jpg", JPEG, "image/jpeg")},
               data={"caption": "hello"})
    assert r.status_code == 200, r.text
    assert post_count() == n0 + 1
    print("inactive OK")

    # --- 3. active: bad photo uploads are refused, no post --------
    settings.GEMINI_API_KEY = "test-key"
    moderation.classify_image = fake_classify
    assert moderation.active()
    for verdict, word in (("adult", "adult"), ("gore", "graphic"),
                          ("error", "couldn't")):
        VERDICT["v"] = verdict
        n0 = post_count()
        r = c.post("/posts/upload", headers=H(555, "Member"),
                   files={"file": ("a.jpg", JPEG, "image/jpeg")},
                   data={"caption": "bad"})
        assert r.status_code == 400, (verdict, r.text)
        assert word in r.json()["detail"], r.json()
        assert post_count() == n0, verdict
    VERDICT["v"] = "clean"
    r = c.post("/posts/upload", headers=H(555, "Member"),
               files={"file": ("a.jpg", JPEG, "image/jpeg")},
               data={"caption": "fine"})
    assert r.status_code == 200, r.text
    print("photo upload screening OK")

    # --- 4. JSON endpoint: file_id is fetched and screened --------
    moderation.fetch_file_bytes = lambda fid: JPEG
    VERDICT["v"] = "adult"
    n0 = post_count()
    r = c.post("/posts", headers=H(555, "Member"),
               json={"type": "photo", "media_file_id": "BAD1",
                     "caption": "sneaky"})
    assert r.status_code == 400 and "adult" in r.json()["detail"]
    assert post_count() == n0
    VERDICT["v"] = "clean"
    r = c.post("/posts", headers=H(555, "Member"),
               json={"type": "photo", "media_file_id": "OK1",
                     "caption": "legit"})
    assert r.status_code == 200, r.text
    # text posts are never screened
    VERDICT["v"] = "adult"
    r = c.post("/posts", headers=H(555, "Member"),
               json={"type": "text", "caption": "just words"})
    assert r.status_code == 200, r.text
    print("json endpoint screening OK")

    # --- 4b. designs (admin-only) skip screening ------------------
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = c.post("/designs/upload", headers=H(777, "Owner"),
               files={"file": ("d.png", PNG, "image/png")},
               data={"prompt": "owner design"})
    assert r.status_code == 200, r.text
    print("design exemption OK")

# --- 5. background video job: bad video never posts ------------------
VERDICT["v"] = "clean"
moderation.screen_video = lambda path: VERDICT["v"]
src = "./_p81_src.bin"
with open(src, "wb") as f:
    f.write(b"\x00" * 128)

VERDICT["v"] = "gore"
SENT.clear()
n0 = post_count()
asyncio.run(main_mod._finish_video_post(555, 555, src, "bad vid"))
assert post_count() == n0
assert any("graphic" in t for _, t in SENT), SENT

with open(src, "wb") as f:
    f.write(b"\x00" * 128)
VERDICT["v"] = "clean"
SENT.clear()
asyncio.run(main_mod._finish_video_post(555, 555, src, "good vid"))
assert post_count() == n0 + 1
assert any("live" in t for _, t in SENT), SENT
print("video job screening OK")

# --- 6. bot-chat route ------------------------------------------------
class FakeTGFile:
    async def download_as_bytearray(self):
        return bytearray(JPEG)


class FakeBotAPI:
    async def get_file(self, file_id):
        return FakeTGFile()


class FakePhoto:
    file_id = "PHOTO1"


class FakeMsg:
    def __init__(self):
        self.caption = ""
        self.photo = [FakePhoto()]
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


class FakeUser:
    id = 556
    username = "botmember"
    first_name = "BotMember"


class FakeUpdate:
    def __init__(self):
        self.effective_user = FakeUser()
        self.message = FakeMsg()


class FakeCtx:
    bot = FakeBotAPI()


VERDICT["v"] = "adult"
upd = FakeUpdate()
n0 = post_count()
asyncio.run(bot_mod.photo_handler(upd, FakeCtx()))
assert post_count() == n0
assert any("adult" in t for t in upd.message.replies), upd.message.replies

VERDICT["v"] = "clean"
upd = FakeUpdate()
asyncio.run(bot_mod.photo_handler(upd, FakeCtx()))
assert post_count() == n0 + 1
assert any("Posted" in t for t in upd.message.replies), upd.message.replies
print("bot route screening OK")

settings.GEMINI_API_KEY = ""
print("PHASE 81 OK")
