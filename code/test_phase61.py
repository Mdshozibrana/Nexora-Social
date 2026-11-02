"""Phase-61 tests: Design gallery pull-to-refresh + interest order
(owner: "Design এ রিফ্রেশ করার অপশন রাখো, নিচের দিকে টানলে রিফ্রেশ
হয়ে যাবে। নতুন রেজাল্ট শো করবে। আর রেজাল্ট ইন্টারেস্ট অনুযায়ী
দেখাবে।").

Server: GET /designs keeps the exact legacy order (newest first,
keyset cursor) for a member with no taste signals. Once a member
has liked or opened designs, the list is personalised: unseen
designs whose prompts match the member's taste (words from liked
prompts weigh 2, opened prompts weigh 1) rank first; seen designs
sink but stay listed; the cursor becomes an offset into the ranked
list. Client: a pull-to-refresh gesture at the top of the Design
view (indicator + touch handlers) reloads the gallery fresh.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"]="sqlite:///./test_phase61.db"
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
FRESH = H(602, "Newbie")

PNG = ("cat.png", b"\x89PNG\r\n\x1a\n fakeimg", "image/png")

with TestClient(app) as c:
    for h in (OWNER, MEMBER, FRESH):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    prompts = ["red rose flower poster", "blue ocean wave seascape",
               "pink rose flower pattern", "snow mountain peak landscape"]
    ids = []
    for i, p in enumerate(prompts):
        r = c.post("/designs/upload", headers=OWNER,
                   files={"file": ("d%d.png" % i, PNG[1], "image/png")},
                   data={"prompt": p})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    d1, d2, d3, d4 = ids

    # --- no signals: exact legacy behaviour (newest first, keyset) ----
    r = c.get("/designs", headers=FRESH)
    assert [d["id"] for d in r.json()["designs"]] == [d4, d3, d2, d1], \
        r.text
    r = c.get("/designs?limit=2", headers=FRESH)
    page = r.json()
    assert [d["id"] for d in page["designs"]] == [d4, d3]
    assert page["next_cursor"] == d3
    r = c.get("/designs?limit=2&cursor=%d" % d3, headers=FRESH)
    page = r.json()
    assert [d["id"] for d in page["designs"]] == [d2, d1]
    # legacy quirk kept: a full page always yields a cursor; the
    # following fetch is empty and closes the list
    r = c.get("/designs?limit=2&cursor=%d" % page["next_cursor"],
              headers=FRESH)
    page = r.json()
    assert page["designs"] == [] and page["next_cursor"] is None

    # --- member likes the rose poster: taste = rose/flower words ------
    r = c.post("/designs/%d/like" % d1, headers=MEMBER, json={})
    assert r.status_code == 200, r.text
    r = c.get("/designs", headers=MEMBER)
    order = [d["id"] for d in r.json()["designs"]]
    # the unseen rose design tops the list; the liked seed sinks last
    assert order[0] == d3, order
    assert order[-1] == d1, order
    assert set(order) == {d1, d2, d3, d4}

    # --- personalised pagination: offset cursor, no duplicates --------
    r = c.get("/designs?limit=2", headers=MEMBER)
    page = r.json()
    first = [d["id"] for d in page["designs"]]
    assert first == order[:2] and page["next_cursor"] == 2, page
    r = c.get("/designs?limit=2&cursor=2", headers=MEMBER)
    page = r.json()
    second = [d["id"] for d in page["designs"]]
    assert second == order[2:], page
    assert page["next_cursor"] is None
    assert not set(first) & set(second)

    # --- opening a design marks it seen: it sinks on the next load ----
    r = c.post("/designs/%d/view" % d4, headers=MEMBER, json={})
    assert r.status_code == 200, r.text
    r = c.get("/designs", headers=MEMBER)
    order2 = [d["id"] for d in r.json()["designs"]]
    assert order2[0] == d3, order2
    assert d4 in order2[2:], order2

    # --- the control member is unaffected by the member's taste -------
    r = c.get("/designs", headers=FRESH)
    assert [d["id"] for d in r.json()["designs"]] == [d4, d3, d2, d1]

# --- frontend wiring: pull-to-refresh on the Design view ---------------
html = open("webapp/index.html").read()
js = open("webapp/app.js").read()
css = open("webapp/style.css").read()
assert 'id="design-ptr"' in html
assert ".ptr-indicator" in css
assert "Pull to refresh" in js and "Release to refresh" in js
assert "Refreshing" in js
ptr_at = js.index('id="design-ptr"') if 'id="design-ptr"' in js \
    else js.index("$(\"design-ptr\")")
assert "loadDesigns(true)" in js[ptr_at:ptr_at + 3000]
assert "touchstart" in js and "touchmove" in js and "touchend" in js

print("PHASE 61 OK")
