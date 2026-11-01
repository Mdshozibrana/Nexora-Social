"""Phase-32 tests: uploads while acting as Official/managed
(owner screenshot: posting as Official died with 'Open
@NexoraSocial_bot once and press Start' — the upload was being
sent to chat 1, the system account, which can never have a bot
chat). The fix: Telegram sends (and result DMs) travel via the
REAL caller's chat; the post still belongs to the acting
identity. file_ids are bot-scoped, so this is sound."""
import asyncio, hashlib, hmac, json, os, shutil, tempfile, time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase32.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from app import notify, tgupload
import app.main as main_mod
import app.videoutil as videoutil_mod

SENT_CHATS = []
DMS = []
# Chats Telegram would refuse: 1 (the official system account can
# never press Start) and 851 (a member who never opened the bot).
REFUSED = {1, 851}


async def fake_upload_media(chat_id, filename, data, content_type):
    SENT_CHATS.append(chat_id)
    if chat_id in REFUSED:
        raise tgupload.TelegramUploadError("not_started")
    kind = tgupload.classify(content_type, filename) or "photo"
    return kind, f"fid_via_{chat_id}"


tgupload.upload_media = fake_upload_media


async def fake_dm(chat_id, text):
    DMS.append((chat_id, text))
    return True


notify.send_message = fake_dm
videoutil_mod.transcode_to_mp4 = lambda s, d: shutil.copyfile(s, d)

from fastapi.testclient import TestClient
from app.main import app

PNG = ("pic.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")


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


OWNER = H(999, "Owner")
OFFICIAL = H(999, "Owner", act_as=1)
MEMBER = H(850, "Mina")
GHOST = H(851, "Ghost")

with TestClient(app) as c:
    for h in (OWNER, MEMBER, GHOST):
        c.post("/auth", json={"initData": h["X-Init-Data"]})

    # 1) A normal member's upload goes via her own chat (unchanged).
    r = c.post("/posts/upload", headers=MEMBER, files={"file": PNG},
               data={"caption": "member photo"})
    assert r.status_code == 200, r.text
    assert SENT_CHATS[-1] == 850, SENT_CHATS
    assert r.json()["author_id"] == 850, r.json()
    print("member upload unchanged OK")

    # 2) THE FIX: acting as Official — the send travels via the
    # owner's real chat (999), the post belongs to Official (1).
    r = c.post("/posts/upload", headers=OFFICIAL, files={"file": PNG},
               data={"caption": "official photo"})
    assert r.status_code == 200, r.text
    assert SENT_CHATS[-1] == 999, SENT_CHATS
    assert r.json()["author_id"] == 1, r.json()
    assert r.json()["media_file_id"] == "fid_via_999", r.json()
    print("official photo post via owner chat OK")

    # 3) Designs: since Phase 34 they are posted ONLY from the
    # admin's own account, so the act-as Official attempt is now
    # refused before any Telegram send (the Phase 32 chat-routing
    # proof lives on in cases 2 and 5, on the post path).
    before = len(SENT_CHATS)
    r = c.post("/designs/upload", headers=OFFICIAL,
               files={"file": PNG}, data={"prompt": "poster prompt"})
    assert r.status_code == 403, r.text
    assert len(SENT_CHATS) == before, SENT_CHATS
    print("official design upload superseded by Phase 34 OK")

    # 4) A member who truly never started the bot still gets the
    # friendly Start message (behaviour preserved).
    r = c.post("/posts/upload", headers=GHOST, files={"file": PNG},
               data={"caption": "ghost photo"})
    assert r.status_code == 400, r.status_code
    assert "press Start" in r.json()["detail"], r.json()
    print("not-started member message preserved OK")

    # 5) Background video path: author stays Official, the send
    # and the result DM go to the owner's real chat.
    with tempfile.NamedTemporaryFile(delete=False,
                                     suffix=".src") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
        src = f.name
    asyncio.run(main_mod._finish_video_post(1, 999, src,
                                            "official clip"))
    assert SENT_CHATS[-1] == 999, SENT_CHATS
    assert DMS and DMS[-1][0] == 999, DMS
    assert "live" in DMS[-1][1], DMS
    # Phase 35: video posts are read back from the Videos source.
    feed = c.get("/feed?type=video", headers=MEMBER).json()["posts"]
    vids = [p for p in feed if p["type"] == "video"]
    assert vids and vids[0]["author_id"] == 1, vids
    print("official video job OK")

print("PHASE-32 TESTS PASSED")
