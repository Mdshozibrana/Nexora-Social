"""Phase 99: Design react button takes its own taps (owner report:
tapping the heart on a Design post landed on the whole post — the
sheet / long-press menu opened instead of the like registering).

Root causes fixed client-side:
- the button was a ~28px sliver (5px vertical padding, 13px font),
  well under a comfortable touch target, so near taps hit the card;
- a slow, careful tap (>450ms) armed the CARD's long-press and the
  fired popup swallowed the like (lpFired check);
- the card's own click had no guard against a click that began on
  the button.

Fixes: the button stops pointerdown/pointerup from ever reaching
the card handlers, the card click ignores any click whose target
is inside the button, and the button is now a 44px touch target.
The card's tap-to-open and hold-for-popup behaviour is unchanged
for every non-button area.
"""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase99.db"
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
    return ("photo", "designfile_" + (file.filename or "x"))


main_mod._telegram_upload_or_400 = fake_upload

from fastapi.testclient import TestClient
from app.main import app

JS = open("webapp/app.js", encoding="utf-8").read()
CSS = open("webapp/style.css", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()

# --- static contract: the button keeps its own taps -------------------
assert 'like.addEventListener("pointerdown", e => e.stopPropagation());' in JS
assert 'like.addEventListener("pointerup", e => e.stopPropagation());' in JS
assert 'e.target.closest(".design-like")' in JS
assert "toggleDesignLike(d); };" in JS
# card behaviours the fix must NOT break: tap opens the sheet,
# hold opens the icon popup
assert "attachLongPress(el, () => showDesignPop(d, el));" in JS
assert "openDesignSheet(d); };" in JS
# 44px touch target
assert ".design-like { min-height: 44px;" in CSS
assert "app.js?v=115" in HTML and "style.css?v=115" in HTML
print("static contract OK")

def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())),
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


client = TestClient(app)
OWNER = H(777, "Owner")
MEMBER = H(555, "Member")
OTHER = H(556, "Other")
for h in (OWNER, MEMBER, OTHER):
    r = client.post("/auth", json={"initData": h["X-Init-Data"]})
    assert r.status_code == 200, r.text

PNG = ("cat.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")
r = client.post("/designs/upload", headers=OWNER,
                files={"file": PNG},
                data={"prompt": "a poster worth reacting to"})
assert r.status_code == 200, r.text
did = r.json()["id"]

# --- the like endpoint the button calls: toggle on/off, per member ---
r = client.post("/designs/%d/like" % did, headers=MEMBER, json={})
assert r.status_code == 200, r.text
assert r.json()["liked"] is True and r.json()["like_count"] == 1, r.text

r = client.get("/designs", headers=MEMBER)
mine = [d for d in r.json()["designs"] if d["id"] == did][0]
assert mine["liked"] is True and mine["like_count"] == 1, mine

r = client.post("/designs/%d/like" % did, headers=OTHER, json={})
assert r.json()["liked"] is True and r.json()["like_count"] == 2, r.text

# the first member's like survives the second member's toggle
r = client.get("/designs", headers=MEMBER)
mine = [d for d in r.json()["designs"] if d["id"] == did][0]
assert mine["liked"] is True and mine["like_count"] == 2, mine

# toggle off again — back to just the other member's like
r = client.post("/designs/%d/like" % did, headers=MEMBER, json={})
assert r.json()["liked"] is False and r.json()["like_count"] == 1, r.text

print("like toggle behaviour OK")
print("PHASE 99 OK")
