"""Phase-25 tests: the Design gallery (owner: a Design tab in the
nav, Pinterest-style premium; designs posted ONLY as the official
account, prompt as the caption). Covers official-only upload
(member AND the admin's own ID are refused), image-only rule,
listing, like toggling, removal by the official identity and by
the admin moderation route, and the frontend wiring (7th nav tab,
masonry CSS, detail sheet with Copy Prompt).
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase25.db"
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


async def fake_upload(user, file, caption=""):
    if (file.filename or "").endswith(".mp4"):
        return ("video", "videofile_x")
    return ("photo", "designfile_" + (file.filename or "x"))


main_mod._telegram_upload_or_400 = fake_upload

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


def H(uid, name, act_as=None):
    h = {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}
    if act_as:
        h["X-Act-As"] = str(act_as)
    return h


OWNER = H(777, "Owner")
OFFICIAL = H(777, "Owner", act_as=1)
MEMBER = H(601, "Ayesha")

PNG = ("cat.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")
MP4 = ("clip.mp4", b"\x00\x00\x00\x18ftypmp42 fakevid", "video/mp4")

with TestClient(app) as c:
    for h in (OWNER, MEMBER):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # --- gallery starts empty; only the official identity can post -----------
    r = c.get("/designs", headers=MEMBER)
    assert r.status_code == 200 and r.json()["designs"] == [], r.text
    r = c.post("/designs/upload", headers=MEMBER,
               files={"file": PNG}, data={"prompt": "member attempt"})
    assert r.status_code == 403, r.status_code
    r = c.post("/designs/upload", headers=OWNER,
               files={"file": PNG}, data={"prompt": "owner own-ID"})
    assert r.status_code == 403, r.status_code  # must be Official
    r = c.post("/designs/upload", headers=OFFICIAL,
               files={"file": MP4}, data={"prompt": "a video"})
    assert r.status_code == 400, r.status_code  # images only
    r = c.post("/designs/upload", headers=OFFICIAL,
               files={"file": PNG},
               data={"prompt": "a majestic cat, studio light, 8k"})
    assert r.status_code == 200, r.text
    design = r.json()
    assert design["prompt"] == "a majestic cat, studio light, 8k", design
    assert design["image_file_id"] == "designfile_cat.png", design
    assert design["author_id"] == 1, design
    did = design["id"]
    print("official-only design upload OK")

    # --- listing + likes -------------------------------------------------------
    r = c.get("/designs", headers=MEMBER)
    rows = r.json()["designs"]
    assert len(rows) == 1 and rows[0]["liked"] is False, rows
    r = c.post(f"/designs/{did}/like", headers=MEMBER)
    assert r.json() == {"liked": True, "like_count": 1}, r.json()
    r = c.get("/designs", headers=MEMBER)
    assert r.json()["designs"][0]["liked"] is True, r.json()
    r = c.post(f"/designs/{did}/like", headers=MEMBER)
    assert r.json() == {"liked": False, "like_count": 0}, r.json()
    r = c.post("/designs/9999/like", headers=MEMBER)
    assert r.status_code == 404, r.status_code
    print("design listing + likes OK")

    # --- removal: member no; official identity yes; admin route yes ------------
    r = c.request("DELETE", f"/designs/{did}", headers=MEMBER)
    assert r.status_code == 403, r.status_code
    r = c.request("DELETE", f"/admin/designs/{did}", headers=MEMBER)
    assert r.status_code == 403, r.status_code
    r = c.request("DELETE", f"/designs/{did}", headers=OFFICIAL)
    assert r.status_code == 200, r.text
    r = c.get("/designs", headers=MEMBER)
    assert r.json()["designs"] == [], r.json()
    r = c.post("/designs/upload", headers=OFFICIAL,
               files={"file": PNG}, data={"prompt": "second design"})
    did2 = r.json()["id"]
    r = c.request("DELETE", f"/admin/designs/{did2}", headers=OWNER)
    assert r.status_code == 200, r.text
    r = c.get("/designs", headers=MEMBER)
    assert r.json()["designs"] == [], r.json()
    print("design removal routes OK")

    # --- frontend wiring -------------------------------------------------------
    html = open("webapp/index.html").read()
    js = open("webapp/app.js").read()
    css = open("webapp/style.css").read()
    for marker in ('id="nav-design"', 'id="view-designs"',
                   'id="design-grid"', 'id="design-upload"',
                   'id="design-switch"', 'id="design-sheet-wrap"',
                   'id="ds-prompt"', 'id="ds-copy"'):
        assert marker in html, marker
    for marker in ("loadDesigns", "openDesignSheet", "Copy Prompt",
                   "toggleDesignLike", 'showView("designs")',
                   '"nav-design"'):
        assert marker in js, marker
    assert "columns: 2" in css and "/ 7)" in css, "masonry/pill CSS"
    print("frontend wiring OK")

print("PHASE 25 ALL OK")
