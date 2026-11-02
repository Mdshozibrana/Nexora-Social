"""Phase-60 tests: the "@@username" bug (owner's search
screenshot: "Ayesha Khanam @@Ayeshakhanam", avatar stacked
above the name). Two causes: (1) a managed account created
with "@name" stored the @ in the username itself — now the
write paths strip it and a startup cleanup repairs existing
rows; (2) a theme layer had set .user-row to display:block —
rows are flex again."""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase60.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

MAIN = open("app/main.py").read()
USERS = open("app/users.py").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()

assert "WHERE username LIKE '@%'" in MAIN
assert 'uname.lstrip("@")' in MAIN
assert 'body.username.strip().lstrip("@")' in MAIN
assert USERS.count('lstrip("@")') == 2
assert 'replace(/^@+/, "")' in JS
assert ".user-row { display: flex;" in CSS
print("wiring pins OK")

# Behaviour: the startup cleanup repairs a stored "@name".
from app.db import SessionLocal
from app import models
import app.main  # importing runs create_all + _migrate (already clean)
db = SessionLocal()
db.add(models.User(telegram_id=31337, first_name="Test",
                   username="@badname"))
db.commit()
db.close()
app.main._migrate()
db = SessionLocal()
u = db.get(models.User, 31337)
assert u.username == "badname", u.username
db.close()
print("cleanup behaviour OK")

print("PHASE-60 TESTS PASSED")
