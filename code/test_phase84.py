"""Phase-84 tests: the design prompt limit (owner: pasting a
long prompt into Design only pasted about half of it).

The cap was 2,000 characters in BOTH prompt boxes (maxlength)
and on the server (the edit path even forwarded only 1,024).
AI prompts routinely run longer, so the limit is now 10,000
everywhere, with a live counter under each box.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase84.db"
os.environ["ADMIN_IDS"] = "777"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import notify

async def fake_send(chat_id, text):
    return True

notify.send_message = fake_send

from app import tgupload

async def fake_upload_media(chat_id, filename, data, content_type):
    kind = tgupload.classify(content_type, filename)
    return (kind, "fileid_" + str(kind), None)

tgupload.upload_media = fake_upload_media

from fastapi.testclient import TestClient
from app.main import app

def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())), "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)

def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid,
                                            "first_name": name})}


HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
MAIN = open("app/main.py").read()

# --- the caps themselves ---------------------------------------------
assert HTML.count('maxlength="10000"') >= 2
assert 'id="design-prompt" rows="3" maxlength="2000"' not in HTML
assert 'id="ds-edit-prompt" rows="4" maxlength="2000"' not in HTML
assert "prompt.strip()[:10000]" in MAIN
assert "prompt.strip()[:2000]" not in MAIN
assert '[:1024]' not in MAIN.split("def edit_design")[1].split(
    "def ")[0]
# live counters wired
assert "wireCharCount" in JS
assert 'id="design-prompt-count"' in HTML
assert 'id="ds-edit-count"' in HTML
assert "app.js?v=101" in HTML and "style.css?v=101" in HTML
print("caps OK")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
OWNER = H(777, "Owner")

with TestClient(app) as c:
    c.post("/posts", headers=OWNER,
           json={"type": "text", "caption": "warm up"})

    long_prompt = ("cinematic portrait, golden light, " * 200)[:6000]
    assert len(long_prompt) == 6000
    r = c.post("/designs/upload", headers=OWNER,
               files={"file": ("d.png", PNG, "image/png")},
               data={"prompt": long_prompt})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    assert r.json()["prompt"] == long_prompt, len(r.json()["prompt"])

    longer = ("ultra detailed digital painting -- " * 250)[:8000]
    assert len(longer) == 8000
    r = c.post(f"/designs/{did}/edit", headers=OWNER,
               data={"prompt": longer})
    assert r.status_code == 200, r.text
    assert r.json()["prompt"] == longer, len(r.json()["prompt"])

    # beyond the new limit: stored at exactly 10,000
    huge = "x" * 12000
    r = c.post(f"/designs/{did}/edit", headers=OWNER,
               data={"prompt": huge})
    assert r.status_code == 200, r.text
    assert len(r.json()["prompt"]) == 10000

    # and the gallery serves the full text back
    r = c.get("/designs", headers=OWNER)
    mine = [d for d in r.json()["designs"] if d["id"] == did]
    assert mine and len(mine[0]["prompt"]) == 10000
print("long prompts OK")
print("PHASE 84 OK")
