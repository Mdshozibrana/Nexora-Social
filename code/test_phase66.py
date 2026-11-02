"""Phase-66 tests: the design LONG-PRESS popup (owner, with a
Pinterest screenshot: "হোল্ড করে ধরলে এসব পপআপ আসবে ... আর সব
যেনো কাজ করে" — hold a design, these icons pop up, and every one
must work).

Server: POST /designs/{id}/save toggles a DesignSave (listed by
GET /me/design-saved; the list payload carries a "saved" flag);
POST /designs/{id}/share mirrors the post share into a
DesignShare (receiver's GET /me/design-shared, bot DM + in-app
notification; self-share 400, unknown target 404);
GET /designs?similar_to=<id> ranks the OTHER designs by prompt
word overlap with the seed (offset cursor); deleting a design
cleans its saves/shares. Client: a 450 ms long-press on a design
card (or the detail image) floats the four round buttons
(🔍 similar, 💬 WhatsApp, 📤 share, 📌 save) over the card's
right side; a similar-mode banner can clear the filter; Saved and
Shared views gain design sections.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_p66.db"
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


OWNER = H(777, "Owner")
MEMBER = H(601, "Ayesha")
OTHER = H(602, "Karim")

with TestClient(app) as c:
    for h in (OWNER, MEMBER, OTHER):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    prompts = ["red rose flower poster", "blue ocean wave seascape",
               "pink rose garden pattern"]
    ids = []
    for i, p in enumerate(prompts):
        r = c.post("/designs/upload", headers=OWNER,
                   files={"file": ("s%d.png" % i, b"\x89PNG fake",
                                   "image/png")},
                   data={"prompt": p})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    d1, d2, d3 = ids

    # --- save toggle + saved flag + saved list ----------------------
    r = c.post("/designs/%d/save" % d1, headers=MEMBER)
    assert r.json() == {"saved": True, "design_id": d1}, r.text
    r = c.get("/designs", headers=MEMBER)
    flags = {d["id"]: d["saved"] for d in r.json()["designs"]}
    assert flags[d1] is True and flags[d2] is False, flags
    r = c.get("/designs", headers=OTHER)
    flags = {d["id"]: d["saved"] for d in r.json()["designs"]}
    assert flags[d1] is False, flags  # saves are per-member
    r = c.get("/me/design-saved", headers=MEMBER)
    assert [d["id"] for d in r.json()["designs"]] == [d1]
    assert r.json()["designs"][0]["saved"] is True
    r = c.post("/designs/%d/save" % d1, headers=MEMBER)
    assert r.json()["saved"] is False
    r = c.get("/me/design-saved", headers=MEMBER)
    assert r.json()["designs"] == []
    r = c.post("/designs/99999/save", headers=MEMBER)
    assert r.status_code == 404
    print("save flow OK")

    # --- share: inbox, self-guard, unknown target -------------------
    r = c.post("/designs/%d/share" % d2, headers=MEMBER,
               json={"to_user_id": 601})
    assert r.status_code == 400, r.text
    r = c.post("/designs/%d/share" % d2, headers=MEMBER,
               json={"to_user_id": 424242})
    assert r.status_code == 404, r.text
    r = c.post("/designs/%d/share" % d2, headers=MEMBER,
               json={"to_user_id": 602})
    assert r.status_code == 200, r.text
    r = c.get("/me/design-shared", headers=OTHER)
    got = r.json()["designs"]
    assert [d["id"] for d in got] == [d2], got
    assert got[0]["shared_by_name"] == "Ayesha"
    r = c.get("/me/notifications", headers=OTHER)
    assert any(n["type"] == "share" and "design" in n["text"]
               for n in r.json()["notifications"]), r.text
    print("share flow OK")

    # --- similar_to: overlap order, seed excluded, offset cursor ----
    r = c.get("/designs?similar_to=%d" % d1, headers=OTHER)
    sims = [d["id"] for d in r.json()["designs"]]
    assert sims == [d3, d2], sims  # rose garden beats ocean
    r = c.get("/designs?similar_to=%d&limit=1" % d1, headers=OTHER)
    page = r.json()
    assert [d["id"] for d in page["designs"]] == [d3]
    assert page["next_cursor"] == 1
    r = c.get("/designs?similar_to=%d&limit=1&cursor=1" % d1,
              headers=OTHER)
    page = r.json()
    assert [d["id"] for d in page["designs"]] == [d2]
    assert page["next_cursor"] is None
    print("similar ranking OK")

    # --- removal cleans saves and shares -----------------------------
    c.post("/designs/%d/save" % d2, headers=MEMBER)
    r = c.delete("/admin/designs/%d" % d2, headers=OWNER)
    assert r.status_code == 200, r.text
    r = c.get("/me/design-saved", headers=MEMBER)
    assert r.json()["designs"] == []
    r = c.get("/me/design-shared", headers=OTHER)
    assert r.json()["designs"] == []
    print("removal cleanup OK")

# --- client pins ------------------------------------------------------
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
for el in ("design-pop", "dp-similar", "dp-wa", "dp-share", "dp-save",
           "design-pop-backdrop", "design-similar-bar",
           "saved-designs", "shared-designs"):
    assert el in HTML, el
assert "attachLongPress(el" in JS and ", 450);" in JS
assert "showDesignPop(d, el)" in JS
assert "wa.me/?text=" in JS
assert '"/designs/" + d.id + "/save"' in JS
assert '"/designs/" + d.id + "/share"' in JS
assert '"&similar_to=" + designSimilar.id' in JS
assert "openDesignSharePicker" in JS
assert 'api("/me/design-saved")' in JS
assert 'api("/me/design-shared")' in JS
assert "if (lpFired) return" in JS
assert "-webkit-touch-callout: none" in CSS
assert ".dp-btn.dp-wa" in CSS and "#25D366" in CSS
print("client pins OK")

print("PHASE 66 OK")
