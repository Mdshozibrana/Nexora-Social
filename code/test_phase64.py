"""Phase-64 tests: a persistent "Open App" button beside the
message input (owner, with a screenshot circling the slot left of
the input: "বটের Open বাটন এখানে দেওয়া যায়?").

That slot is Telegram's chat menu button. At bot startup we call
set_chat_menu_button with a MenuButtonWebApp pointing at the Mini
App; Telegram stores it server-side and shows it in every private
chat with the bot. The welcome message's inline Open App button
stays as it was. The call is guarded: if it fails, polling still
starts. With no WEBAPP_URL configured, no call is made.
"""
import asyncio, os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"]="sqlite:///./test_phase64.db"

from app.config import settings
import app.bot as bot_mod


class FakeBot:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def set_chat_menu_button(self, menu_button=None, **kw):
        if self.fail:
            raise RuntimeError("telegram said no")
        self.calls.append(menu_button)
        return True


class FakeUpdater:
    def __init__(self):
        self.polled = False

    async def start_polling(self, **kw):
        self.polled = True


class FakeApp:
    def __init__(self, fail=False):
        self.bot = FakeBot(fail)
        self.updater = FakeUpdater()
        self.initialized = False
        self.started = False

    async def initialize(self):
        self.initialized = True

    async def start(self):
        self.started = True


# --- happy path: the button is set, then polling starts -------------
settings.WEBAPP_URL = "https://example.com/webapp/"
app = FakeApp()
asyncio.run(bot_mod.start_bot(app))
assert app.initialized and app.updater.polled and app.started
assert len(app.bot.calls) == 1
mb = app.bot.calls[0]
assert mb.type == "web_app", mb.type
assert mb.text == "Open App"
assert mb.web_app.url == "https://example.com/webapp/"
print("menu button set OK")

# --- a Telegram failure must not stop the bot -----------------------
app = FakeApp(fail=True)
asyncio.run(bot_mod.start_bot(app))
assert app.updater.polled and app.started
print("failure guard OK")

# --- no webapp URL configured: no call, bot still starts ------------
settings.WEBAPP_URL = ""
app = FakeApp()
asyncio.run(bot_mod.start_bot(app))
assert app.bot.calls == [] and app.updater.polled
print("no-url skip OK")

# --- the welcome message keeps its inline Open App button -----------
src = open("app/bot.py").read()
assert "set_chat_menu_button" in src and "MenuButtonWebApp" in src
assert "\\U0001F680 Open App" in src  # the /start inline button
print("source wiring OK")

print("PHASE 64 OK")
