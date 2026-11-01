"""Phase-34 tests: Design posting rule (owner directive):
ONLY the admin's own ID can post designs — acting-as (Official or
managed) cannot — and the admin's identity is shown NOWHERE in the
Design tab. Regular members keep everything else, exactly like
other posts: browse, open (view), like, read the prompt."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase34.db"

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
HTML = open("webapp/index.html").read()

# --- client contract: upload card keys on the admin's own ID ---
assert "me.is_admin) && !actAsId()" in JS
assert 'id="design-switch"' not in HTML
assert "design-switch" not in JS
assert "posted without your name or ID" in HTML
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


def H(uid, name, act_as=None):
    h = {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}
    if act_as:
        h["X-Act-As"] = str(act_as)
    return h


ADMIN = H(999, "ShozibAdmin")
OFFICIAL = H(999, "ShozibAdmin", act_as=1)
MEMBER = H(870, "RegularMember")
PNG = ("d.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")

with TestClient(app) as c:
    for h in (ADMIN, MEMBER):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # A managed account to act as.
    r = c.post("/admin/fake-users", headers=ADMIN,
               json={"first_name": "Managed One", "count": 1})
    assert r.status_code == 200, r.text
    managed_id = r.json()["created"][0]["telegram_id"]
    MANAGED = H(999, "ShozibAdmin", act_as=managed_id)

    # --- only the admin's own ID may post ---
    r = c.post("/designs/upload", headers=MEMBER,
               files={"file": PNG}, data={"prompt": "member try"})
    assert r.status_code == 403, r.status_code
    r = c.post("/designs/upload", headers=OFFICIAL,
               files={"file": PNG}, data={"prompt": "official try"})
    assert r.status_code == 403, r.status_code
    r = c.post("/designs/upload", headers=MANAGED,
               files={"file": PNG}, data={"prompt": "managed try"})
    assert r.status_code == 403, r.status_code
    r = c.post("/designs/upload", headers=ADMIN,
               files={"file": PNG}, data={"prompt": "admin design"})
    assert r.status_code == 200, r.text
    design = r.json()
    did = design["id"]
    print("admin-only posting OK")

    # --- the admin's identity appears NOWHERE ---
    # The response reports only the platform identity...
    assert design["author_id"] == 1, design
    assert design["author_name"] == "Nexora Social", design
    # ...and neither the admin's id nor name leaks anywhere in the
    # upload response or the member-facing listing.
    blob = json.dumps(design)
    assert "999" not in blob and "ShozibAdmin" not in blob, blob
    r = c.get("/designs", headers=MEMBER)
    blob = json.dumps(r.json())
    assert "999" not in blob and "ShozibAdmin" not in blob, blob
    assert r.json()["designs"][0]["id"] == did
    print("poster identity hidden OK")

    # --- members keep everything else, like other posts ---
    r = c.post(f"/designs/{did}/like", headers=MEMBER)
    assert r.json() == {"liked": True, "like_count": 1}, r.json()
    r = c.post(f"/designs/{did}/view", headers=MEMBER)
    assert r.json() == {"views": 1, "counted": True}, r.json()
    r = c.get("/designs", headers=MEMBER)
    row = r.json()["designs"][0]
    assert row["prompt"] == "admin design", row
    assert row["like_count"] == 1 and row["views"] == 1, row
    print("member browse/like/view OK")

print("PHASE-34 TESTS PASSED")
