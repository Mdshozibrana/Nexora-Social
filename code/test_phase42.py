"""Phase-42 tests: the name changes once every 60 days (owner).
First change is free (the clock starts there); a second, different
name inside 60 days is refused with the remaining days; bio-only
edits and unchanged-name saves stay free during the lock; after
60 days the name can change again and the clock restarts."""
import hashlib, hmac, json, os, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase42.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models

JS = open("webapp/app.js").read()
assert "name_locked_days" in JS and "60 days" in JS
print("client contract OK")


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid,
                                           "first_name": name})}


A = H(880, "Alice")

with TestClient(app) as c:
    c.post("/auth", json={"initData": A["X-Init-Data"]})

    # first change: free, and the clock starts
    r = c.post("/me/profile", headers=A, json={"first_name": "Alicia"})
    assert r.status_code == 200 and r.json()["first_name"] == "Alicia", r.text
    r = c.get("/users/880", headers=A)
    assert r.json()["name_locked_days"] == 60, r.json()

    # a different name inside 60 days: refused, with the wait
    r = c.post("/me/profile", headers=A, json={"first_name": "Ally"})
    assert r.status_code == 400, r.status_code
    assert "60 days" in r.json()["detail"], r.json()
    # the name did not move
    r = c.get("/users/880", headers=A)
    assert r.json()["first_name"] == "Alicia"

    # bio-only edits stay free during the lock…
    r = c.post("/me/profile", headers=A, json={"bio": "hello"})
    assert r.status_code == 200, r.text
    # …and re-saving the SAME name is a no-op, not a violation
    r = c.post("/me/profile", headers=A,
               json={"first_name": "Alicia", "bio": "hi2"})
    assert r.status_code == 200 and r.json()["bio"] == "hi2", r.text
    print("60-day lock OK")

    # 61 days later: changeable again, and the clock restarts
    db = SessionLocal()
    u = db.get(models.User, 880)
    u.name_changed_at = datetime.utcnow() - timedelta(days=61)
    db.commit()
    db.close()
    r = c.get("/users/880", headers=A)
    assert r.json()["name_locked_days"] == 0, r.json()
    r = c.post("/me/profile", headers=A, json={"first_name": "Ally"})
    assert r.status_code == 200 and r.json()["first_name"] == "Ally", r.text
    r = c.post("/me/profile", headers=A, json={"first_name": "Third"})
    assert r.status_code == 400, r.status_code
    print("lock expiry + restart OK")

print("PHASE-42 TESTS PASSED")
