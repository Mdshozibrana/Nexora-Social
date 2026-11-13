"""Phase-69 tests: Nexa, the 3D AI assistant (owner: "এমন একটা
3D girls AI এড করতে পারো যে কথা বলবে সরাসরি সবার সাথে। আর এই AI
Assistant শুধু সাইডবার ওপেন করলে বের হবে। সুন্দর বাচ্চাদের মতো
রিয়েলস্টিক ভয়েস হবে।").

Client: her card (photo + name) sits inside the sidebar, so she
is visible only when the sidebar is open; tapping it opens the
assistant view — her stage picture (wave/idle/think/talk poses),
chat bubbles, quick chips, input + voice toggle. Replies are
spoken (talking pose while audio plays).

Server: GET /assistant/status, POST /assistant/chat and
/assistant/speak. Brain + voice are Gemini when GEMINI_API_KEY
is set (stubbed here); without a key the chat uses the built-in
bilingual guide brain and speak returns {audio: None} so the
client falls back to the phone's own voice.
"""
import base64, hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///test_phase69.db"
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
from app.config import settings
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


client = TestClient(app)
h = H(42, "Member")

# --- client markers ---------------------------------------------------
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
assert 'class="gb-item gb-nexa" data-go="assistant"' in HTML
assert 'src="nexa/idle.webp"' in HTML
seg = HTML[HTML.index('id="view-assistant"'):HTML.index('id="view-messages"')]
for bit in ('id="nexa-img"', 'src="nexa/wave.webp"', 'id="nexa-log"',
            'id="nexa-input"', 'id="nexa-send"',
            'class="nexa-chip"'):
    assert bit in seg, bit
assert seg.count('class="nexa-chip"') == 4
for bit in ("openAssistant()", "sendNexa",
            '"/assistant/chat"',
            '"chat", "assistant", "nearby", "museum"]'):
    assert bit in JS, bit
for bit in (".gb-nexa-img", ".nexa-stage", "@keyframes nexaTalk",
            ".nexa-msg.me", ".nexa-msg.bot"):
    assert bit in CSS, bit
for pose in ("idle", "talk", "wave", "think"):
    assert os.path.exists(f"webapp/nexa/{pose}.webp"), pose
assert "style.css?v=111" in HTML and "app.js?v=111" in HTML
print("client markers OK")

# --- auth + fallback brain (no key) ------------------------------------
assert settings.GEMINI_API_KEY == ""
r = client.get("/assistant/status")
assert r.status_code == 401, r.status_code
r = client.get("/assistant/status", headers=h)
assert r.status_code == 200 and r.json() == {"name": "Nexa", "ai": False}

r = client.post("/assistant/chat", headers=h, json={"message": "  "})
assert r.status_code == 400
r = client.post("/assistant/chat", headers=h,
                json={"message": "How do I earn points?"})
assert r.status_code == 200, r.text
j = r.json()
assert j["ai"] is False and "20" in j["reply"] and "point" in j["reply"].lower()
r = client.post("/assistant/chat", headers=h,
                json={"message": "পয়েন্ট কীভাবে পাবো?"})
j = r.json()
assert "পয়েন্ট" in j["reply"] and "২০" in j["reply"], j
r = client.post("/assistant/chat", headers=h,
                json={"message": "Hi Nexa!"})
assert "Nexa" in r.json()["reply"]
r = client.post("/assistant/chat", headers=h,
                json={"message": "zqx wobble nonsense"})
assert "learning" in r.json()["reply"]
r = client.post("/assistant/speak", headers=h, json={"text": "Hello!"})
assert r.status_code == 200 and r.json() == {"audio": None}
print("fallback brain OK")

# --- Gemini brain + voice (stubbed HTTP) --------------------------------
class FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p


real_post = main_mod.httpx.post
calls = []


def fake_post(url, headers=None, json=None, timeout=None):
    calls.append(url)
    if "tts" not in url and url.endswith(":generateContent"):
        assert headers["x-goog-api-key"] == "test-key-69"
        assert json["system_instruction"]["parts"][0]["text"] \
            .startswith("You are Nexa")
        return FakeResp({"candidates": [{"content": {"parts": [
            {"text": "Hello! I am so happy to chat with you."}]}}]})
    if "tts" in url and url.endswith(":generateContent"):
        vc = json["generationConfig"]["speechConfig"]["voiceConfig"]
        assert vc["prebuiltVoiceConfig"]["voiceName"] == "Leda"
        pcm = b"\x00\x01" * 2400  # 0.1 s of 24 kHz 16-bit mono
        return FakeResp({"candidates": [{"content": {"parts": [
            {"inlineData": {"data": base64.b64encode(pcm).decode(),
                            "mimeType": "audio/L16;rate=24000"}}]}}]})
    raise AssertionError("unexpected url " + url)


settings.GEMINI_API_KEY = "test-key-69"
main_mod.httpx.post = fake_post
try:
    r = client.get("/assistant/status", headers=h)
    assert r.json() == {"name": "Nexa", "ai": True}
    r = client.post("/assistant/chat", headers=h,
                    json={"message": "Tell me a secret",
                          "history": [{"role": "user", "text": "hi"},
                                      {"role": "nexa", "text": "hello"}]})
    j = r.json()
    assert j["ai"] is True and j["reply"].startswith("Hello!"), j
    r = client.post("/assistant/speak", headers=h,
                    json={"text": "Hello friend"})
    j = r.json()
    assert j["mime"] == "audio/wav" and j["audio"]
    raw = base64.b64decode(j["audio"])
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE", raw[:12]
    assert len(calls) == 2
finally:
    main_mod.httpx.post = real_post
    settings.GEMINI_API_KEY = ""
print("gemini brain + voice OK")

print("PHASE 69 OK")
