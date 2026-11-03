"""Phase-72 tests: Nexa answers faster and knows the whole
site (owner: "উত্তর দিতে সময় বেশি নেয়" + "Nexa কে পুরো
সাইট সম্পর্কে শেখাও"), and pull-to-refresh works on every
main page like Design's.

Speed: the chat models spent 300+ tokens "thinking" before
each short reply (measured live: 322 thought tokens). The
generation config now sets thinkingBudget 0 — verified live
against the real API (200, zero thought tokens, full answer) —
with a 400-safe retry without the field. Knowledge: her system
prompt is now a complete manual of the app (navigation, feed,
posting incl. the bot-chat route, reels, designs, points,
referrals, the 6 monetization targets, verification at 1000
followers, messages/stories, the 10 games, profile rules,
search, saved/shared, safety, account), and the guide-mode
fallback brain learned verification, stories, profile editing
and blocking. PTR: a global indicator + loader map mirrors the
Design handler for feed, videos, tasks, leaderboard, saved,
shared, notifications, messages, profile and admin.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///test_phase72.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from app import notify


async def fake_send(chat_id, text):
    return True


notify.send_message = fake_send

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

# --- speed config + full manual in the source -------------------------
assert '"thinkingBudget": 0' in MAIN
for topic in ("1000 followers", "60 days", "lamp cord",
              "NexoraSocial_bot", "12 qualified referrals",
              "500 followers", "24 hours", "Pac-Man",
              "Monetization", "VERIFICATION"):
    assert topic in MAIN, topic
print("manual + speed OK")

# --- guide brain knows the new topics ---------------------------------
r = client.post("/assistant/chat", headers=h,
                json={"message": "How do I get verified?"})
assert r.status_code == 200 and "1000" in r.json()["reply"], r.text
r = client.post("/assistant/chat", headers=h,
                json={"message": "কীভাবে স্টোরি দেবো?"})
assert r.status_code == 200 and "২৪" in r.json()["reply"]
r = client.post("/assistant/chat", headers=h,
                json={"message": "How do I block someone?"})
assert r.status_code == 200 and "Block" in r.json()["reply"]
r = client.post("/assistant/chat", headers=h,
                json={"message": "প্রোফাইল ছবি বদলাবো কীভাবে?"})
assert r.status_code == 200 and "ক্যামেরা" in r.json()["reply"]
print("fallback topics OK")

# --- pull-to-refresh everywhere ---------------------------------------
assert 'id="ptr-global"' in HTML
for view in ("feed", "videos", "tasks", "leaderboard", "saved",
             "shared", "notifications", "messages", "profile",
             "admin"):
    assert view + ":" in JS, view
# (loader map entries)
for fn in ("loadFeed(true)", "loadVideos(true)", "loadTasks()",
           "loadRanks()", "loadSaved()", "loadShared()",
           "loadNotifications(true)", "loadMessages()",
           "openProfile(me.telegram_id)", "loadAdmin()"):
    assert fn in JS, fn
assert "ptr-global" in JS and "Pull to refresh" in JS
# design keeps its own handler
assert 'id="design-ptr"' in HTML
print("ptr OK")

assert "app.js?v=78" in HTML and "style.css?v=78" in HTML
print("PHASE 72 OK")
