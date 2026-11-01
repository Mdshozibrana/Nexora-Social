"""Phase-51 tests: video previews (owner: no preview before
play — the player showed a blank pink frame). Telegram makes a
thumbnail for every video; it is now stored on the post on
every creation path and shipped in post_dict, the client sets
it as the player's poster, and posts without one get a
seek-paint fallback."""
import asyncio, hashlib, hmac, json, os, shutil, tempfile, time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase51.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from app import notify, tgupload
import app.main as main_mod
import app.videoutil as videoutil_mod


async def fake_upload_media(chat_id, filename, data, content_type):
    return "video", "VID51", "THUMB51"


tgupload.upload_media = fake_upload_media


async def fake_dm(chat_id, text):
    return True


notify.send_message = fake_dm
videoutil_mod.transcode_to_mp4 = lambda s, d: shutil.copyfile(s, d)

JS = open("webapp/app.js").read()
assert JS.count("vid.poster = mediaUrl(p.thumb_file_id)") == 2
assert "loadedmetadata" in JS and "currentTime = 0.1" in JS
BOT = open("app/bot.py").read()
assert "video.thumbnail" in BOT and "thumb_file_id=thumb" in BOT
print("client + bot contracts OK")

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


with TestClient(app) as c:
    init = make_init_data({"id": 999, "first_name": "Owner"})
    c.post("/auth", json={"initData": init})
    H = {"X-Init-Data": init}

    # the background video job stores Telegram's thumbnail
    fd, src = tempfile.mkstemp(suffix=".src")
    os.write(fd, b"fake video bytes")
    os.close(fd)
    asyncio.run(main_mod._finish_video_post(999, 999, src,
                                            "clip with preview"))
    db = SessionLocal()
    post = db.query(models.Post).filter_by(type="video").first()
    assert post is not None and post.media_file_id == "VID51", post
    assert post.thumb_file_id == "THUMB51", post.thumb_file_id
    db.close()

    r = c.get("/feed?type=video", headers=H)
    assert r.status_code == 200, r.text
    item = r.json()["posts"][0]
    assert item["thumb_file_id"] == "THUMB51", item
    print("upload path stores + serves thumbnail OK")

print("PHASE-51 TESTS PASSED")
