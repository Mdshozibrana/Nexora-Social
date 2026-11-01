"""Phase-16 tests: in-app media upload (posts + profile photo) and the
/media proxy fix. The Telegram upload helper is stubbed (no network);
httpx is faked for /media so the streamed body must arrive intact —
the old handler closed its client before streaming and broke images.
Also asserts the composer 📷 attach UI and Change-photo wiring.

REGRESSION LOCK (Oct 31, production): the first /media fix built the
download URL as /bot<token>/file/<path>; Telegram's real layout is
/file/bot<token>/<path>, so production answered 404 for every photo
while this suite stayed green — the fake accepted ANY url. The fake
below is now strict: getFile must be /bot<token>/getFile and the file
download must be exactly /file/bot<token>/photos/file_1.jpg, anything
else gets a Telegram-style 404."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase16.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

import httpx
from app import tgupload

FAKE_ID = "FAKE_UPLOADED_FILE_ID"
STATE = {"mode": "ok"}

async def fake_upload(chat_id, filename, data, content_type):
    if STATE["mode"] == "not_started":
        raise tgupload.TelegramUploadError("not_started")
    return tgupload.classify(content_type), FAKE_ID

tgupload.upload_media = fake_upload

# Phase 27: videos are scheduled as background jobs; swallow them
# in this suite (the fake clip bytes are not a real video).
import app.main as _main_mod
_main_mod._schedule_video_job = lambda coro: coro.close()


class FakeGetFileResp:
    status_code = 200

    def json(self):
        return {"result": {"file_path": "photos/file_1.jpg"}}


class FakeStreamResp:
    status_code = 200
    headers = {"content-type": "image/jpeg", "content-length": "5"}

    async def aiter_bytes(self):
        yield b"ab"
        yield b"cde"

    async def aclose(self):
        pass


class Fake404Resp:
    status_code = 404
    headers = {"content-type": "application/json"}

    async def aiter_bytes(self):
        yield b'{"ok":false}'

    async def aclose(self):
        pass


class FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        token = os.environ["BOT_TOKEN"]
        assert url == f"https://api.telegram.org/bot{token}/getFile", url
        assert params and params.get("file_id"), params
        return FakeGetFileResp()

    def build_request(self, method, url, headers=None):
        return (method, url, headers)

    async def send(self, req, stream=False):
        token = os.environ["BOT_TOKEN"]
        expected = f"https://api.telegram.org/file/bot{token}/photos/file_1.jpg"
        if req[1] != expected:
            return Fake404Resp()
        return FakeStreamResp()

    async def aclose(self):
        pass


httpx.AsyncClient = FakeAsyncClient

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


AMY = H(888, "Amy")

with TestClient(app) as c:
    # --- /media streams the file bytes end to end ---
    r = c.get("/media/SOME_FILE_ID")
    assert r.status_code == 200, r.status_code
    assert r.content == b"abcde", r.content
    assert r.headers["content-type"] == "image/jpeg"
    print("/media streams bytes intact OK")

    # --- in-app photo upload creates a media post (+5 points) ---
    before = c.post("/auth", json={"initData": AMY["X-Init-Data"]}).json()["points"]
    r = c.post("/posts/upload", headers=AMY, data={"caption": "hello #sun"},
               files={"file": ("pic.jpg", b"\xff\xd8\xff\xe0jpegbytes",
                               "image/jpeg")})
    assert r.status_code == 200, r.text
    post = r.json()
    assert post["type"] == "photo" and post["media_file_id"] == FAKE_ID, post
    assert post["caption"] == "hello #sun"
    after = c.post("/auth", json={"initData": AMY["X-Init-Data"]}).json()["points"]
    assert after == before + 5, (before, after)
    print("photo upload post + points OK")

    # --- video upload accepted (Phase 27: 202 background path) ---
    r = c.post("/posts/upload", headers=AMY, data={"caption": "clip"},
               files={"file": ("v.mp4", b"\x00\x00\x00\x18ftypmp42",
                               "video/mp4")})
    assert r.status_code == 202 and \
        r.json()["status"] == "processing", r.text
    print("video upload accepted (background) OK")

    # --- unsupported type, oversize, and bot-not-started errors ---
    r = c.post("/posts/upload", headers=AMY, data={"caption": "x"},
               files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400, r.status_code
    old_max = tgupload.MAX_MEDIA_BYTES
    tgupload.MAX_MEDIA_BYTES = 4
    r = c.post("/posts/upload", headers=AMY, data={"caption": "x"},
               files={"file": ("p.jpg", b"12345", "image/jpeg")})
    assert r.status_code == 400 and "20 MB" in r.json()["detail"], r.text
    tgupload.MAX_MEDIA_BYTES = old_max
    STATE["mode"] = "not_started"
    r = c.post("/posts/upload", headers=AMY, data={"caption": "x"},
               files={"file": ("p.jpg", b"\xff\xd8", "image/jpeg")})
    assert r.status_code == 400 and "Start" in r.json()["detail"], r.text
    STATE["mode"] = "ok"
    print("upload validation + friendly errors OK")

    # --- profile photo change from inside the app ---
    r = c.post("/me/photo/upload", headers=AMY,
               files={"file": ("me.png", b"\x89PNG\r\n\x1a\n", "image/png")})
    assert r.status_code == 200 and r.json()["photo_file_id"] == FAKE_ID, r.text
    me = c.post("/auth", json={"initData": AMY["X-Init-Data"]}).json()
    assert me["photo_file_id"] == FAKE_ID
    r = c.post("/me/photo/upload", headers=AMY,
               files={"file": ("v.mp4", b"\x00\x00", "video/mp4")})
    assert r.status_code == 400, "profile upload must reject videos"
    print("profile photo upload OK")

    # --- frontend wiring ---
    js = c.get("/webapp/app.js").text
    for marker in ("/posts/upload", "/me/photo/upload", "composer-media",
                   "composerFile", "apiForm", "Change profile photo"):
        assert marker in js, marker
    html = c.get("/webapp/").text
    for marker in ("composer-file", "composer-media", "composer-attach",
                   "profile-file"):
        assert marker in html, marker
    css = c.get("/webapp/style.css").text
    for marker in (".composer-row", ".tool-btn", ".attach-chip"):
        assert marker in css, marker
    print("frontend upload wiring OK")

print("PHASE-16 TESTS PASSED")
