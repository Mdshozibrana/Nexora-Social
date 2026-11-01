"""Phase-11 tests: profile pictures (Telegram photo sync endpoint, real
photo file_id flowing into profiles and post cards), the verified mark
for admin/owner accounts (incl. comments), and the Games page assets."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase11.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import photosync

async def fake_fetch(telegram_id):
    return "TG_PHOTO_FILE_1" if telegram_id == 888 else None

photosync.fetch_telegram_photo_file_id = fake_fetch

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())), "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}

ROOT, AMY, NED = H(777, "Root"), H(888, "Amy"), H(999, "Ned")

with TestClient(app) as c:
    r = c.post("/auth", json={"initData": ROOT["X-Init-Data"]})
    assert r.json()["is_verified"] is True, "admin/owner account must be verified"
    r = c.post("/auth", json={"initData": AMY["X-Init-Data"]})
    assert r.json()["is_verified"] is False
    assert r.json()["photo_file_id"] is None
    c.post("/auth", json={"initData": NED["X-Init-Data"]})
    print("verified mark: owner yes, regular member no OK")

    r = c.post("/me/photo/sync", headers=AMY)
    assert r.json() == {"photo_file_id": "TG_PHOTO_FILE_1"}, r.json()
    prof = c.get("/users/888", headers=NED).json()
    assert prof["photo_file_id"] == "TG_PHOTO_FILE_1"
    post = c.post("/posts", headers=AMY,
                  json={"type": "text", "caption": "Amy here"}).json()
    assert post["author_photo"] == "TG_PHOTO_FILE_1", post
    r = c.post("/me/photo/sync", headers=NED)
    assert r.json() == {"photo_file_id": None}
    print("profile photo sync + author_photo on posts OK")

    cm = c.post(f"/posts/{post['id']}/comments", headers=ROOT,
                json={"text": "Official word"}).json()
    assert cm["author_verified"] is True, cm
    cms = c.get(f"/posts/{post['id']}/comments", headers=AMY).json()["comments"]
    assert cms[0]["author_verified"] is True
    print("verified badge data on comments OK")

    r = c.get("/webapp/games.js")
    assert r.status_code == 200 and "Snake" in r.text and "Tetris" in r.text
    r = c.get("/webapp/")
    assert "nav-games" in r.text and "view-games" in r.text
    print("games page assets served OK")

print("PHASE-11 TESTS PASSED")
