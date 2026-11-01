"""Phase-27 tests: upload resilience (owner's screenshot showed the
XHR dying at network level — "Upload failed — check your
connection" — with the video already attached).

Covers: every video now takes the 202 background path (the request
ends when the bytes arrive instead of waiting on the Telegram
send), and X-Upload-Id dedupe on /posts/upload + /designs/upload —
the client's automatic fetch retry (and any manual re-tap after a
dropped response) replays the stored result instead of creating a
duplicate post or scheduling a second video job.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase27.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import notify

async def fake_send(chat_id, text):
    return True

notify.send_message = fake_send

import app.main as main_mod
from app import tgupload

async def fake_upload_media(chat_id, filename, data, content_type):
    kind = tgupload.classify(content_type, filename)
    return (kind, "fileid_" + str(kind))

tgupload.upload_media = fake_upload_media

JOBS = []

def capture_job(coro):
    JOBS.append(coro)
    coro.close()

main_mod._schedule_video_job = capture_job

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


def H(uid, name, act_as=None, upload_id=None):
    h = {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}
    if act_as:
        h["X-Act-As"] = str(act_as)
    if upload_id:
        h["X-Upload-Id"] = upload_id
    return h


MEMBER = H(601, "Ayesha")
OFFICIAL = H(777, "Owner", act_as=1)
PNG = ("pic.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")
MP4 = ("clip.mp4", b"\x00\x00\x00\x18ftypmp42 fake", "video/mp4")

with TestClient(app) as c:
    c.post("/auth", json={"initData": MEMBER["X-Init-Data"]})
    c.post("/auth", json={"initData": H(777, "Owner")["X-Init-Data"]})

    # --- photo dedupe: same upload id replays, never duplicates ----------------
    h1 = H(601, "Ayesha", upload_id="up-photo-1")
    r1 = c.post("/posts/upload", headers=h1, files={"file": PNG},
                data={"caption": "dedupe me"})
    r2 = c.post("/posts/upload", headers=h1, files={"file": PNG},
                data={"caption": "dedupe me"})
    assert r1.status_code == 200 and r2.status_code == 200, \
        (r1.text, r2.text)
    assert r1.json()["id"] == r2.json()["id"], (r1.json(), r2.json())
    r = c.get("/feed", headers=MEMBER)
    mine = [p for p in r.json()["posts"]
            if p["caption"] == "dedupe me"]
    assert len(mine) == 1, mine
    # a different id is a genuinely new post
    h2 = H(601, "Ayesha", upload_id="up-photo-2")
    r3 = c.post("/posts/upload", headers=h2, files={"file": PNG},
                data={"caption": "dedupe me"})
    assert r3.json()["id"] != r1.json()["id"], r3.json()
    print("photo upload dedupe OK")

    # --- video: always the 202 background path, deduped too ---------------------
    hv = H(601, "Ayesha", upload_id="up-video-1")
    r1 = c.post("/posts/upload", headers=hv, files={"file": MP4},
                data={"caption": "a video"})
    assert r1.status_code == 202, r1.text
    assert r1.json()["status"] == "processing", r1.json()
    assert len(JOBS) == 1, JOBS
    r2 = c.post("/posts/upload", headers=hv, files={"file": MP4},
                data={"caption": "a video"})
    assert r2.status_code == 202, r2.text
    assert len(JOBS) == 1, "retry must not schedule a second job"
    print("video 202 path + dedupe OK")

    # --- design dedupe ---------------------------------------------------------
    hd = H(777, "Owner", act_as=1, upload_id="up-design-1")
    r1 = c.post("/designs/upload", headers=hd, files={"file": PNG},
                data={"prompt": "one design"})
    r2 = c.post("/designs/upload", headers=hd, files={"file": PNG},
                data={"prompt": "one design"})
    assert r1.status_code == 200 and r2.status_code == 200, \
        (r1.text, r2.text)
    assert r1.json()["id"] == r2.json()["id"], (r1.json(), r2.json())
    r = c.get("/designs", headers=MEMBER)
    assert len(r.json()["designs"]) == 1, r.json()
    print("design upload dedupe OK")

    # --- frontend wiring ---------------------------------------------------------
    js = open("webapp/app.js").read()
    for marker in ("X-Upload-Id", "newUploadId", "fetchRetry",
                   "composerUploadId", "designUploadId"):
        assert marker in js, marker
    print("frontend wiring OK")

print("PHASE 27 ALL OK")
