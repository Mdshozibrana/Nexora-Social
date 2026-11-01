"""Phase-40 tests: profile cover photo + writable bio (owner:
add a cover-photo option to the user profile, and make the bio
writable). Covers the migration column, cover upload + public
profile exposure, self-service name/bio editing with its guards,
and the client wiring."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase40.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.main as main_mod


async def fake_upload(user, file, caption=""):
    return ("photo", "coverfile_1")


main_mod._telegram_upload_or_400 = fake_upload

from fastapi.testclient import TestClient
from app.main import app

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
for marker in ('id="cover-file"',):
    assert marker in HTML, marker
for marker in ("profile-cover", "/me/cover/upload", "/me/profile",
               "Change cover photo", "Edit name & bio"):
    assert marker in JS, marker
assert ".profile-cover" in CSS and ".profile-edit" in CSS
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
B = H(881, "Bob")
PNG = ("c.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")

with TestClient(app) as c:
    for h in (A, B):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # --- bio: writable by the member herself ---
    r = c.get("/users/880", headers=B)
    assert r.json()["bio"] == "" and r.json()["cover_file_id"] is None
    r = c.post("/me/profile", headers=A,
               json={"bio": "  Gardener & dreamer 🌿  "})
    assert r.status_code == 200 and \
        r.json()["bio"] == "Gardener & dreamer 🌿", r.text
    r = c.get("/users/880", headers=B)
    assert r.json()["bio"] == "Gardener & dreamer 🌿", r.json()
    r = c.post("/me/profile", headers=A, json={"first_name": "  "})
    assert r.status_code == 400, r.status_code
    r = c.post("/me/profile", headers=A,
               json={"first_name": "Alice A.", "bio": "New bio"})
    assert r.json() == {"first_name": "Alice A.", "bio": "New bio"}
    r = c.post("/me/profile", headers=A, json={"bio": "x" * 501})
    assert r.status_code == 422, r.status_code  # pydantic cap
    print("bio + name editing OK")

    # --- cover photo ---
    r = c.post("/me/cover/upload", headers=A, files={"file": PNG})
    assert r.status_code == 200, r.text
    assert r.json() == {"cover_file_id": "coverfile_1"}, r.json()
    r = c.get("/users/880", headers=B)
    assert r.json()["cover_file_id"] == "coverfile_1", r.json()
    # someone else's cover is untouched
    r = c.get("/users/881", headers=A)
    assert r.json()["cover_file_id"] is None, r.json()
    print("cover upload OK")

print("PHASE-40 TESTS PASSED")
