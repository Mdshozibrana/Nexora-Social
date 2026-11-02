"""Phase-59 tests: post editing (owner: the post ⋮ menu has
no Edit). The author can fix the caption from the options
sheet; hashtags re-extract; likes stay; anyone else gets a
404, exactly like delete."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase59.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

JS = open("webapp/app.js").read()
for marker in ('row("✏️", "Edit"', "openPostEditor",
               '"/posts/" + p.id + "/edit"', "sheet-edit-ta"):
    assert marker in JS, marker
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
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


AUTHOR = H(111, "Author")
OTHER = H(222, "Other")

with TestClient(app) as c:
    for h in (AUTHOR, OTHER):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    r = c.post("/posts", headers=AUTHOR,
               json={"type": "text", "caption": "hello world #old"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["hashtags"] == "old"
    c.post(f"/posts/{pid}/like", headers=OTHER)

    # someone else's post: not found, and nothing changes
    r = c.post(f"/posts/{pid}/edit", headers=OTHER,
               json={"caption": "hacked #evil"})
    assert r.status_code == 404, r.status_code
    # a missing post: also 404
    r = c.post("/posts/424242/edit", headers=AUTHOR,
               json={"caption": "x"})
    assert r.status_code == 404, r.status_code

    # the author edits: caption + hashtags update, like survives
    r = c.post(f"/posts/{pid}/edit", headers=AUTHOR,
               json={"caption": "fixed caption #new #fresh"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["caption"] == "fixed caption #new #fresh", body
    assert body["hashtags"] == "new fresh", body
    assert body["like_count"] == 1, body

    # clearing the caption works too
    r = c.post(f"/posts/{pid}/edit", headers=AUTHOR, json={"caption": ""})
    assert r.status_code == 200 and r.json()["caption"] == "", r.text
    assert r.json()["hashtags"] == ""
    print("post edit behaviour OK")

print("PHASE-59 TESTS PASSED")
