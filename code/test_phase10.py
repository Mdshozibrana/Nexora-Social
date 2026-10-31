"""Phase-10 tests: in-app sharing — Share sends a post to another member
inside Nexora Social: following list for the picker, share delivery to
the receiver's 'Shared with me' inbox, bot notification, guards."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase10.db"

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

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}

ANN, BEN, CY = H(101, "Ann"), H(202, "Ben"), H(303, "Cy")

with TestClient(app) as c:
    for h in (ANN, BEN, CY):
        assert c.post("/auth", json={"initData": h["X-Init-Data"]}).status_code == 200

    post = c.post("/posts", headers=ANN, json={
        "type": "video", "media_file_id": "VID10", "caption": "Ann reel"}).json()
    c.post("/users/101/follow", headers=BEN)

    fol = c.get("/me/following", headers=BEN).json()["users"]
    ids = [u["telegram_id"] for u in fol]
    assert ids == [101], ids  # Ann only; the official account is excluded
    print("share picker list (following, official excluded) OK")

    r = c.post(f"/posts/{post['id']}/share", headers=BEN,
               json={"to_user_id": 303})
    assert r.json() == {"ok": True, "post_id": post["id"], "to_user_id": 303}, r.json()
    assert any(cid == 303 and "shared a video" in txt for cid, txt in SENT), SENT
    print("share delivered + bot notification to receiver OK")

    inbox = c.get("/me/shared", headers=CY).json()["posts"]
    assert len(inbox) == 1 and inbox[0]["id"] == post["id"], inbox
    assert inbox[0]["shared_by_name"] == "Ben" and inbox[0]["type"] == "video"
    assert c.get("/me/shared", headers=BEN).json()["posts"] == []
    assert c.get("/me/shared", headers=ANN).json()["posts"] == []
    print("receiver inbox shows the shared post with sender name OK")

    r = c.post(f"/posts/{post['id']}/share", headers=BEN, json={"to_user_id": 202})
    assert r.status_code == 400
    r = c.post(f"/posts/{post['id']}/share", headers=BEN, json={"to_user_id": 99999})
    assert r.status_code == 404
    print("share guards: self 400, unknown user 404 OK")

    c.delete(f"/posts/{post['id']}", headers=ANN)
    assert c.get("/me/shared", headers=CY).json()["posts"] == []
    r = c.post(f"/posts/{post['id']}/share", headers=BEN, json={"to_user_id": 303})
    assert r.status_code == 404
    print("deleted posts leave the inbox and cannot be shared OK")

print("PHASE-10 TESTS PASSED")
