"""Phase-33 tests: client-side photo shrink before upload
(owner's second screenshot: after the Phase 32 fix, the same
Official photo post now died with 'Upload failed — check your
connection' — the client-side message produced ONLY when both the
XHR and the fetch retry die at network level, i.e. the request
never reached the server; a multi-MB camera JPG is the payload
that fragile path drops). Photos now shrink to max 1600px in the
browser before sending. Client contract is static; plus a smoke
check that the server side is untouched."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase33.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app

JS = open("webapp/app.js").read()
MAIN = open("app/main.py").read()

# --- shrink helper contract ---
assert "async function shrinkForUpload" in JS
assert "MAX = 1600" in JS
assert "toBlob" in JS and "image/jpeg" in JS and "image/png" in JS
# HEIC passes through (the server converts it); tiny files too.
assert "heic|heif" in JS
assert "700 * 1024" in JS
# Any failure falls back to the untouched original.
assert "catch (e) { return file; }" in JS
# All three upload call sites route through the shrink.
assert 'form.append("file", await shrinkForUpload(composerFile))' in JS
assert 'fd.append("file", await shrinkForUpload(designFile))' in JS
assert 'form.append("file", await shrinkForUpload(f))' in JS
# Videos are never shrunk (non-image types return immediately).
assert "!/^image\\//" in JS
print("shrink contract OK")

# --- Phase 32 server routing still in place ---
assert "_send_chat_id" in MAIN and "_real_id" in MAIN
print("phase32 routing intact OK")


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


with TestClient(app) as c:
    d = make_init_data({"id": 860, "first_name": "Smoke"})
    h = {"X-Init-Data": d}
    assert c.post("/auth", json={"initData": d}).status_code == 200
    r = c.post("/posts", headers=h,
               json={"type": "text", "caption": "phase33 smoke"})
    assert r.status_code == 200, r.text
    assert c.get("/feed", headers=h).status_code == 200
print("api smoke OK")

print("PHASE-33 TESTS PASSED")
