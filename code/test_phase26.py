"""Phase-26 tests: the composer upload repair (owner: "ভিডিও
আপলোড হচ্ছে না, Post বাটন কাজ করে না — Image-এও").

Root causes covered: phone pickers often report an empty/generic
MIME type, so kind detection now falls back to the file-name
extension on the client AND the server; HEIC/HEIF phone photos are
accepted and converted to JPEG before the Telegram send; a small
.mp4 with a generic MIME type takes the fast path; the composer
never fails silently any more (a feedback line under the Post
button, an attach confirmation, and an upload timeout).
"""
import hashlib, hmac, json, os, urllib.parse
from io import BytesIO

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase26.db"
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
from app import tgupload

captured = {}

async def fake_upload_media(chat_id, filename, data, content_type):
    captured.update(filename=filename, data=data,
                    content_type=content_type)
    kind = tgupload.classify(content_type, filename)
    return (kind, "fileid_" + str(kind))

tgupload.upload_media = fake_upload_media

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


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid,
                                            "first_name": name})}


MEMBER = H(601, "Ayesha")

# --- classify: MIME first, extension fallback --------------------------------
assert tgupload.classify("image/jpeg", "") == "photo"
assert tgupload.classify("", "VID_2026.mp4") == "video"
assert tgupload.classify("application/octet-stream",
                         "IMG_2041.HEIC") == "photo"
assert tgupload.classify("image/heic", "x") == "photo"
assert tgupload.classify("", "notes.txt") is None
assert tgupload.classify("video/quicktime", "") == "video"
print("classify fallbacks OK")

with TestClient(app) as c:
    c.post("/auth", json={"initData": MEMBER["X-Init-Data"]})

    # --- HEIC photo: converted to JPEG, then posted ---------------------------
    from PIL import Image
    from pillow_heif import register_heif_opener
    register_heif_opener()
    buf = BytesIO()
    Image.new("RGB", (48, 36), (40, 120, 200)).save(buf, format="HEIF")
    heic_bytes = buf.getvalue()
    assert heic_bytes[4:12].startswith(b"ftyp"), heic_bytes[4:12]
    r = c.post("/posts/upload", headers=MEMBER,
               files={"file": ("IMG_2041.HEIC", heic_bytes, "image/heic")},
               data={"caption": "my heic photo"})
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "photo", r.json()
    assert captured["content_type"] == "image/jpeg", captured
    assert captured["data"][:2] == b"\xff\xd8", "not JPEG bytes"
    assert captured["filename"].endswith(".jpg"), captured
    print("HEIC -> JPEG upload OK")

    # --- .mp4 with a generic MIME type takes the fast path ---------------------
    r = c.post("/posts/upload", headers=MEMBER,
               files={"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42",
                               "application/octet-stream")},
               data={"caption": "generic mime video"})
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "video", r.json()
    assert captured["content_type"] == "video/mp4", captured
    print("generic-MIME mp4 fast path OK")

    # --- photo with a generic MIME type, recognised by extension ---------------
    r = c.post("/posts/upload", headers=MEMBER,
               files={"file": ("pic.png", b"\x89PNG\r\n\x1a\n fake",
                               "application/octet-stream")},
               data={"caption": "generic mime photo"})
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "photo", r.json()
    print("generic-MIME photo upload OK")

    # --- unsupported files still refused, with a clear message ------------------
    r = c.post("/posts/upload", headers=MEMBER,
               files={"file": ("notes.txt", b"hello", "text/plain")},
               data={"caption": "nope"})
    assert r.status_code == 400, r.status_code
    assert "HEIC" in r.json()["detail"], r.json()
    print("unsupported type refusal OK")

    # --- frontend wiring ---------------------------------------------------------
    html = open("webapp/index.html").read()
    js = open("webapp/app.js").read()
    assert 'id="composer-status"' in html
    for marker in ("composerStatus(", "xhr.timeout", "ontimeout",
                   "attach a photo/video first",
                   "Attached ✓ — now tap Post."):
        assert marker in js, marker
    print("frontend wiring OK")

print("PHASE 26 ALL OK")
