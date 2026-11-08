"""Phase 100: Data Control — the export actually works now
(owner: "Data Control থেকে ডাটা এক্সপোর্ট হয়না").

The /me/export endpoint existed since Phase 28, and Nexa's manual
even promised an export from the profile — but the client never
had a single export (or delete-account) button anywhere, so a
member had no way to use it. This phase builds the missing card
in My Profile extras and adds the phone-reliable delivery route:
- GET  /me/export        (unchanged payload, now rate-limited)
- POST /me/export/send   (same JSON sent as a file to the
                          member's Telegram chat via the bot)
- Data Control card: Download + Send-to-Telegram buttons, and a
  typed-DELETE account deletion (endpoint also from Phase 28).
"""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase100.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from app import notify

SENT = []


async def fake_send_document(chat_id, filename, data, caption=""):
    SENT.append((chat_id, filename, data, caption))
    return True


notify.send_document = fake_send_document


async def fake_send(chat_id, text):
    return True


notify.send_message = fake_send

from fastapi.testclient import TestClient
from app.main import app

JS = open("webapp/app.js", encoding="utf-8").read()
CSS = open("webapp/style.css", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()
MAIN = open("app/main.py", encoding="utf-8").read()
CONF = open("app/config.py", encoding="utf-8").read()

# --- static contract ---------------------------------------------------
assert "function dataCard()" in JS
assert "wrap.appendChild(dataCard());" in JS
assert "🗂️ Data Control" in JS
assert 'api("/me/export")' in JS
assert 'api("/me/export/send", { method: "POST" })' in JS
assert 'a.download = "nexora-export.json"' in JS
assert 'api("/me/delete-account", { method: "POST",' in JS
assert 'delInput.value !== "DELETE"' in JS
assert ".data-btn { min-height: 44px;" in CSS
assert '"export": (10, 3600)' in CONF
assert "async def send_document(" in open(
    "app/notify.py", encoding="utf-8").read()
assert "def _export_payload(" in MAIN
assert '@app.post("/me/export/send")' in MAIN
assert "Data Control card" in MAIN  # Nexa manual tells the truth now
assert "app.js?v=102" in HTML and "style.css?v=102" in HTML
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
MEMBER = H(555, "Exporter")
for h in (MEMBER,):
    r = client.post("/auth", json={"initData": h["X-Init-Data"]})
    assert r.status_code == 200, r.text

# give the member something worth exporting
r = client.post("/posts", headers=MEMBER, json={
    "type": "text", "media_file_id": "", "caption": "my first post"})
assert r.status_code in (200, 201), r.text

# --- download route: full payload, attachment header -------------------
r = client.get("/me/export", headers=MEMBER)
assert r.status_code == 200, r.text
assert "attachment" in r.headers.get("content-disposition", "")
payload = r.json()
assert payload["profile"]["telegram_id"] == 555, payload["profile"]
assert payload["profile"]["first_name"] == "Exporter"
assert any(p["caption"] == "my first post" for p in payload["posts"])
for key in ("comments", "points_ledger", "following", "followers",
            "exported_at"):
    assert key in payload, key
print("download export OK")

# --- send route: the file reaches the member's Telegram chat -----------
r = client.post("/me/export/send", headers=MEMBER, json={})
assert r.status_code == 200 and r.json()["sent"] is True, r.text
assert len(SENT) == 1
chat_id, filename, data, caption = SENT[0]
assert chat_id == 555 and filename == "nexora-export.json"
sent_payload = json.loads(data.decode("utf-8"))
assert sent_payload["profile"]["telegram_id"] == 555
print("send-to-telegram export OK")

# --- send route when the bot cannot reach the member -------------------
async def fail_send_document(chat_id, filename, data, caption=""):
    return False


notify.send_document = fail_send_document
r = client.post("/me/export/send", headers=MEMBER, json={})
assert r.status_code == 200 and r.json()["sent"] is False, r.text
notify.send_document = fake_send_document
print("send-failure honesty OK")

# --- unauthenticated: no export for strangers ---------------------------
r = client.get("/me/export")
assert r.status_code == 401, r.status_code
r = client.post("/me/export/send", json={})
assert r.status_code == 401, r.status_code

# --- rate budget: a fresh member gets 10 exports/hour, then 429 --------
FRESH = H(556, "Fresh")
r = client.post("/auth", json={"initData": FRESH["X-Init-Data"]})
assert r.status_code == 200, r.text
for i in range(10):
    r = client.get("/me/export", headers=FRESH)
    assert r.status_code == 200, (i, r.status_code)
r = client.get("/me/export", headers=FRESH)
assert r.status_code == 429, r.status_code
print("export rate limit OK")

# --- delete account (the card's other half): typed confirm rules -------
r = client.post("/me/delete-account", headers=MEMBER,
                json={"confirm": "delete"})
assert r.status_code == 400, r.status_code
r = client.post("/me/delete-account", headers=MEMBER,
                json={"confirm": "DELETE"})
assert r.status_code == 200 and r.json()["deleted"] == 555, r.text
# the wiped data stays wiped: a later request with the same
# Telegram identity can only ever see a brand-new empty account
# (the app's auth auto-provisions), never the deleted history
r = client.get("/me/export", headers=MEMBER)
assert r.status_code == 200, r.status_code
fresh = r.json()
assert fresh["posts"] == [] and fresh["comments"] == [], fresh
assert fresh["profile"]["points_balance"] == 0, fresh["profile"]
print("delete-account flow OK")

print("PHASE 100 OK")
