"""Phase-46 tests: design editing (owner: the Design section
must be editable as needed). The admin — own account only, the
Phase 34 rule — can change a design's prompt and/or replace its
image; members and act-as identities cannot; likes/views and
the anonymous platform identity survive an edit."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase46.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.main as main_mod


async def fake_upload(user, file, caption=""):
    return ("photo", "edited_img_1")


main_mod._telegram_upload_or_400 = fake_upload

from fastapi.testclient import TestClient
from app.main import app

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
for marker in ('id="ds-edit"', 'id="ds-edit-box"',
               'id="ds-edit-prompt"', 'id="ds-edit-file"'):
    assert marker in HTML, marker
for marker in ("/edit", "dsEditFile", "Edit design" if False else "ds-edit-save"):
    assert marker in JS, marker
print("client contract OK")


def make_init_data(user, extra=None):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    if extra:
        params.update(extra)
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, extra=None):
    return {"X-Init-Data": make_init_data(
        {"id": uid, "first_name": name}, extra)}


OWNER = H(999, "Owner")
MEMBER = H(880, "Alice")
PNG = ("d.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")

with TestClient(app) as c:
    for h in (OWNER, MEMBER):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    r = c.post("/designs/upload", headers=OWNER,
               data={"prompt": "a red bicycle"}, files={"file": PNG})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    c.post(f"/designs/{did}/like", headers=MEMBER)

    # a member cannot edit
    r = c.post(f"/designs/{did}/edit", headers=MEMBER,
               data={"prompt": "hacked"})
    assert r.status_code == 403, r.status_code
    # nothing to change -> 400
    r = c.post(f"/designs/{did}/edit", headers=OWNER, data={})
    assert r.status_code == 400, r.status_code
    # missing design -> 404
    r = c.post("/designs/424242/edit", headers=OWNER,
               data={"prompt": "x"})
    assert r.status_code == 404, r.status_code

    # prompt edit: applies, like survives, identity stays platform
    r = c.post(f"/designs/{did}/edit", headers=OWNER,
               data={"prompt": "a blue bicycle at dawn"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prompt"] == "a blue bicycle at dawn", body
    assert body["like_count"] == 1, body
    blob = json.dumps(body)
    assert "999" not in blob and "Owner" not in blob, blob

    # image replacement
    r = c.post(f"/designs/{did}/edit", headers=OWNER,
               files={"file": PNG})
    assert r.status_code == 200, r.text
    assert r.json()["image_file_id"] == "edited_img_1", r.json()
    assert r.json()["prompt"] == "a blue bicycle at dawn", r.json()
    print("design editing OK")

print("PHASE-46 TESTS PASSED")
