"""Phase-71 tests: Nexa's cut-off answers and missing voice
(owner: "Nexa পুরো উত্তর দেয়না আর ভয়েস আসেনা").

Root causes, both proven live against the owner's real key:
(1) gemini-3-flash-preview spends its output budget THINKING —
at maxOutputTokens 220 a Bengali answer used 207 thought
tokens and 9 answer tokens, finishReason MAX_TOKENS, cut off
mid-word. Budget is now 1500 and the reply slice is 900.
(2) Voice needed TWO sequential round trips (chat, then speak)
after the member's tap, so playback began seconds late and the
WebView refused it; and the spoken text was capped at 300
chars while replies could run longer. Now POST
/assistant/reply returns text + audio in one call, the speak
cap is 650, the unlock clip is a real 50 ms WAV, and every Nexa
bubble is tappable to hear her say it (a fresh tap always
passes the audio gate).
"""
import base64, hashlib, hmac, io, json, os, urllib.parse, wave

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///test_phase71.db"
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

MAIN = open("app/main.py").read()
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()

# --- the truncation fix is in the source ------------------------------
assert '"maxOutputTokens": 1500' in MAIN
assert '"/assistant/reply"' in MAIN
assert "max_length=700" in MAIN
print("server config OK")

# --- fallback mode: reply endpoint answers text, audio null -----------
r = client.post("/assistant/reply", headers=h,
                json={"message": "How do I earn points?"})
assert r.status_code == 200, r.text
j = r.json()
assert j["ai"] is False and j["audio"] is None and "20" in j["reply"]
r = client.post("/assistant/reply", headers=h, json={"message": " "})
assert r.status_code == 400
print("reply fallback OK")

# --- Gemini mode (stubbed): one call, text + WAV together --------------
class FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p


real_post = main_mod.httpx.post
seen = []


def fake_post(url, headers=None, json=None, timeout=None):
    seen.append(url)
    if "tts" in url:
        pcm = b"\x00\x01" * 2400
        return FakeResp({"candidates": [{"content": {"parts": [
            {"inlineData": {"data": base64.b64encode(pcm).decode(),
                            "mimeType": "audio/L16;rate=24000"}}]}}]})
    assert json["generationConfig"]["maxOutputTokens"] == 1500
    return FakeResp({"candidates": [{"content": {"parts": [
        {"text": "Full answer, every word of it."}]}}]})


settings.GEMINI_API_KEY = "test-key-71"
main_mod.httpx.post = fake_post
try:
    long_text = "Please say this whole long sentence. " * 14  # 504 chars
    r = client.post("/assistant/speak", headers=h,
                    json={"text": long_text})
    assert r.status_code == 200 and r.json()["audio"], r.status_code
    r = client.post("/assistant/reply", headers=h,
                    json={"message": "Tell me everything"})
    j = r.json()
    assert j["ai"] is True
    assert j["reply"] == "Full answer, every word of it."
    raw = base64.b64decode(j["audio"])
    assert raw[:4] == b"RIFF" and j["mime"] == "audio/wav"
    assert len(seen) == 3  # speak(1) + reply chat(1) + reply tts(1)
finally:
    main_mod.httpx.post = real_post
    settings.GEMINI_API_KEY = ""
print("reply gemini OK")

# --- client: replies render as text bubbles -------------------
assert '"/assistant/chat"' in JS
print("client markers OK")

assert "app.js?v=78" in HTML and "style.css?v=78" in HTML
print("PHASE 71 OK")
