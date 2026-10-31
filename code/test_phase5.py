"""Phase-5 tests: bot notifications (with hourly cap), admin endpoints
(ban, remove post, report queue + resolve, broadcast)."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase5.db"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

import app.notify as notify_mod

SENT = []

async def fake_send(chat_id, text):
    SENT.append((chat_id, text))
    return True

notify_mod.send_message = fake_send

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


ALICE = make_init_data({"id": 111, "first_name": "Alice", "username": "alice"})
BOB = make_init_data({"id": 222, "first_name": "Bob", "username": "bob"})
HA = {"X-Init-Data": ALICE}
HB = {"X-Init-Data": BOB}

with TestClient(app) as c:
    c.post("/auth", json={"initData": ALICE})
    c.post("/auth", json={"initData": BOB})

    r = c.post("/admin/ban", headers=HB, json={"telegram_id": 111})
    assert r.status_code == 403, r.status_code
    print("non-admin blocked from admin endpoints OK")

    post = c.post("/posts", headers=HA,
                  json={"type": "text", "caption": "Admin test post"}).json()
    pid = post["id"]

    c.post(f"/posts/{pid}/like", headers=HB)
    assert len(SENT) == 1 and SENT[0][0] == 111 and "liked" in SENT[0][1], SENT
    c.post(f"/posts/{pid}/like", headers=HB)  # unlike: silent
    assert len(SENT) == 1
    c.post(f"/posts/{pid}/comments", headers=HB, json={"text": "Nice!"})
    assert len(SENT) == 2 and "commented" in SENT[1][1]
    c.post(f"/posts/{pid}/like", headers=HA)  # self-like: silent
    assert len(SENT) == 2
    c.post("/users/111/follow", headers=HB)
    assert len(SENT) == 3 and "following" in SENT[2][1]
    print("like/comment/follow notifications OK (self-actions silent)")

    db = SessionLocal()
    logs = db.query(models.NotificationLog).filter_by(user_id=111).count()
    assert logs == 3, logs
    db.close()

    saved_cap = notify_mod.MAX_PER_HOUR
    notify_mod.MAX_PER_HOUR = 3
    try:
        c.post(f"/posts/{pid}/like", headers=HB)  # unlike
        c.post(f"/posts/{pid}/like", headers=HB)  # like again: capped
        assert len(SENT) == 3, SENT
    finally:
        notify_mod.MAX_PER_HOUR = saved_cap
    print("hourly notification cap OK")

    rep = c.post("/reports", headers=HB,
                 json={"post_id": pid, "reason": "spam"}).json()
    rows = c.get("/admin/reports", headers=HA).json()["reports"]
    assert len(rows) == 1 and rows[0]["id"] == rep["id"]
    assert rows[0]["post_caption"] == "Admin test post"
    r = c.post(f"/admin/reports/{rep['id']}/resolve", headers=HA,
               json={"action": "remove_post"})
    assert r.json()["status"] == "resolved"
    feed = c.get("/feed", headers=HA).json()["posts"]
    assert all(p["id"] != pid for p in feed)
    rows = c.get("/admin/reports?status=resolved", headers=HA).json()["reports"]
    assert len(rows) == 1
    print("report queue + resolve(remove_post) OK")

    post2 = c.post("/posts", headers=HB,
                   json={"type": "text", "caption": "Bob post"}).json()
    r = c.post(f"/admin/posts/{post2['id']}/remove", headers=HA)
    assert r.json()["ok"] is True
    feed = c.get("/feed", headers=HA).json()["posts"]
    assert all(p["id"] != post2["id"] for p in feed)
    print("admin direct post removal OK")

    r = c.post("/admin/ban", headers=HA, json={"telegram_id": 222, "banned": True})
    assert r.json()["is_banned"] is True
    r = c.get("/feed", headers=HB)
    assert r.status_code == 403, r.status_code
    c.post("/admin/ban", headers=HA, json={"telegram_id": 222, "banned": False})
    r = c.get("/feed", headers=HB)
    assert r.status_code == 200
    print("ban/unban OK")

    SENT.clear()
    r = c.post("/admin/broadcast", headers=HA, json={"text": "Hello everyone"})
    body = r.json()
    assert body == {"recipients": 2, "sent": 2}, body  # official account excluded
    assert {cid for cid, _ in SENT} == {111, 222}
    print("broadcast OK")

print("PHASE-5 TESTS PASSED")
