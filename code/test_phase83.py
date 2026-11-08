"""Phase-83 tests: upload progress signals (owner: "কতটুকু
আপলোড হলো এমন আপলোড % বা অন্য কোনো সংকেত দেখাবে").

In-app: the composer gains a real progress bar — the true byte
% while uploading, an animated Posting… state while the server
finishes, then Posted ✓ / 🎬 Processing — and story uploads
report their % instead of silence. In the bot chat, a media post
opens a "⏳ Posting…" message that is edited into the outcome.
"""
import asyncio, os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase83.db"
os.environ["ADMIN_IDS"] = "777"
os.environ["GEMINI_API_KEY"] = ""

JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()

# --- client: the bar exists and is driven by real progress -------
for bit in ('id="composer-progress"', 'id="composer-progress-fill"',
            'id="composer-progress-label"'):
    assert bit in HTML, bit
for bit in ('lab.textContent = "Uploading… " + pct + "%"',
            'fill.classList.add("busy")', '"Posted ✓"',
            '"🎬 Processing video…"',
            '$("composer-progress").hidden = true;'):
    assert bit in JS, bit
# stories report their % too (the callback used to be a no-op)
assert '"Posting your story… " + pct + "%"' in JS
assert 'apiFormProgress("/stories/upload", form, () => {}, null)' \
    not in JS
for bit in (".up-progress", "#composer-progress-fill.busy",
            "@keyframes upslide"):
    assert bit in CSS, bit
assert "app.js?v=100" in HTML and "style.css?v=100" in HTML
print("client OK")

# --- bot: one status message, edited into the outcome --------------
assert "⏳ Posting your {ptype}…" in BOT
assert "status_msg.edit_text(text)" in BOT
print("bot source OK")

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from app import notify

async def fake_send(chat_id, text):
    return True

notify.send_message = fake_send

import app.main as main_mod  # noqa: F401 — importing builds the tables
from app import moderation
from app.config import settings
from app.db import SessionLocal
from app import models


def post_count():
    db = SessionLocal()
    try:
        return db.query(models.Post).count()
    finally:
        db.close()


class FakeStatus:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text):
        self.edits.append(text)


class FakeTGFile:
    async def download_as_bytearray(self):
        return bytearray(b"\xff\xd8\xff\xe0" + b"\x00" * 32)


class FakeBotAPI:
    async def get_file(self, file_id):
        return FakeTGFile()


class FakePhoto:
    file_id = "PHOTO1"


class FakeMsg:
    def __init__(self):
        self.caption = ""
        self.photo = [FakePhoto()]
        self.sent = []
        self.status = FakeStatus()

    async def reply_text(self, text):
        self.sent.append(text)
        return self.status


class FakeUser:
    id = 557
    username = "progressfan"
    first_name = "ProgressFan"


class FakeUpdate:
    def __init__(self):
        self.effective_user = FakeUser()
        self.message = FakeMsg()


class FakeCtx:
    bot = FakeBotAPI()


settings.GEMINI_API_KEY = "test-key"
VERDICT = {"v": "clean"}
moderation.classify_image = lambda data, mime="image/jpeg": VERDICT["v"]

# warm-up: creates the member and triggers the one-time
# welcome-post seeding, so the counts below are stable
asyncio.run(bot_mod.photo_handler(FakeUpdate(), FakeCtx()))

upd = FakeUpdate()
n0 = post_count()
asyncio.run(bot_mod.photo_handler(upd, FakeCtx()))
assert upd.message.sent[0].startswith("⏳ Posting your photo"), \
    upd.message.sent
assert any("Posted to" in t for t in upd.message.status.edits), \
    upd.message.status.edits
assert post_count() == n0 + 1

VERDICT["v"] = "adult"
upd = FakeUpdate()
asyncio.run(bot_mod.photo_handler(upd, FakeCtx()))
assert any("wasn't posted" in t for t in upd.message.status.edits), \
    upd.message.status.edits
assert post_count() == n0 + 1
print("bot flow OK")

settings.GEMINI_API_KEY = ""
print("PHASE 83 OK")
