"""Phase-31 tests: Pinterest-true Design gallery + UNIQUE view
counting (owner: designs arranged like the Pinterest screenshots,
the detail caption opens partly with See more, video views are
shown, and every unique view counts — once per member, never per
replay)."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "777"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase31.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from app import notify


async def fake_send(chat_id, text):
    return True


notify.send_message = fake_send

import app.main as main_mod


async def fake_upload(user, file, caption=""):
    return ("photo", "designfile_" + (file.filename or "x"))


main_mod._telegram_upload_or_400 = fake_upload

from fastapi.testclient import TestClient
from app.main import app

JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
HTML = open("webapp/index.html").read()

# --- client wiring (static contract) ---
assert "function markViewed" in JS and "viewedItems" in JS
assert 'markViewed("designs", d.id' in JS          # sheet open = view
assert 'markViewed("posts", p.id' in JS            # feed video play
assert "en.target.dataset.pid" in JS               # reel on screen
assert "ds-more" in HTML and "ds-views" in HTML    # sheet elements
assert "See more" in JS and "See less" in JS
assert "Phase 31" in CSS and "#ds-prompt.clamped" in CSS
assert "design-stats" in CSS and "design-views" in JS
print("client wiring OK")


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, act_as=None):
    h = {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}
    if act_as:
        h["X-Act-As"] = str(act_as)
    return h


OWNER = H(777, "Owner")
OFFICIAL = H(777, "Owner", act_as=1)
A = H(801, "Ayesha")
B = H(802, "Bilal")
PNG = ("poster.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")

with TestClient(app) as c:
    for h in (OWNER, A, B):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # --- design views: unique per member ---
    # Phase 34: designs post from the admin's own id (no act-as).
    r = c.post("/designs/upload", headers=OWNER,
               files={"file": PNG}, data={"prompt": "sunset poster"})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    assert r.json()["views"] == 0, r.json()
    r = c.post(f"/designs/{did}/view", headers=A)
    assert r.json() == {"views": 1, "counted": True}, r.json()
    r = c.post(f"/designs/{did}/view", headers=A)
    assert r.json() == {"views": 1, "counted": False}, r.json()
    r = c.post(f"/designs/{did}/view", headers=B)
    assert r.json() == {"views": 2, "counted": True}, r.json()
    r = c.get("/designs", headers=A)
    assert r.json()["designs"][0]["views"] == 2, r.json()
    r = c.post("/designs/99999/view", headers=A)
    assert r.status_code == 404, r.status_code
    print("design unique views OK")

    # --- post (video) views: unique per member, shown in feed ---
    r = c.post("/posts", headers=A, json={
        "type": "video", "media_file_id": "vid31",
        "caption": "my clip"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["views"] == 0, r.json()
    r = c.post(f"/posts/{pid}/view", headers=B)
    assert r.json() == {"views": 1, "counted": True}, r.json()
    r = c.post(f"/posts/{pid}/view", headers=B)
    assert r.json() == {"views": 1, "counted": False}, r.json()
    r = c.post(f"/posts/{pid}/view", headers=A)
    assert r.json() == {"views": 2, "counted": True}, r.json()
    feed = c.get("/feed", headers=B).json()["posts"]
    mine = [p for p in feed if p["id"] == pid][0]
    assert mine["views"] == 2, mine
    r = c.post("/posts/99999/view", headers=A)
    assert r.status_code == 404, r.status_code
    print("post unique views OK")

    # --- wiping a member removes their views everywhere ---
    r = c.delete("/admin/users/802", headers=OWNER)
    assert r.status_code == 200, r.text
    r = c.get("/designs", headers=A)
    assert r.json()["designs"][0]["views"] == 1, r.json()
    feed = c.get("/feed", headers=A).json()["posts"]
    mine = [p for p in feed if p["id"] == pid][0]
    assert mine["views"] == 1, mine
    print("wipe cleans views OK")

print("PHASE-31 TESTS PASSED")
