"""Phase 97: whole-bot audit fixes.

Findings fixed here:
1. The bare domain root returned a JSON 404 — it now redirects to
   the app.
2. The bot's #profile photo route skipped the ban check and the
   Phase 81 media screening that every other upload passes.
3. The two newest endpoints (Phase 95 suggestions, Phase 96 theme
   saves) had no rate-limit budget.
4. Archery progress in games.js used plain shared localStorage keys
   — the same cross-account leak the theme had before Phase 96.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase97.db"
os.environ["ADMIN_IDS"] = "999"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

import app.main as main_mod
from app.main import app
from app.config import RATE_LIMITS

MAIN = open("app/main.py", encoding="utf-8").read()
BOT = open("app/bot.py", encoding="utf-8").read()
GAMES = open("webapp/games.js", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()

# 1) root redirect
assert '@app.get("/")' in MAIN and "RedirectResponse" in MAIN
# 2) bot #profile guards: ban check + screening inside photo_handler
profile_block = BOT.split('if "#profile" in caption:')[1].split("await _save_media_post")[0]
assert "is_banned" in profile_block, "ban check missing in #profile"
assert "_screen_via_bot" in profile_block, "screening missing in #profile"
assert "moderation.active()" in profile_block
# 3) rate budgets
assert RATE_LIMITS["suggested"] == (120, 3600)
assert RATE_LIMITS["theme"] == (120, 3600)
assert '_enforce_rate("suggested"' in MAIN
assert '_enforce_rate("theme"' in MAIN
# 4) per-account archery keys
for bit in ("nxUid", "nxGet", "nxSet", 'nxGet("nx_archery_run")',
            'nxSet("nx_archery_best"'):
    assert bit in GAMES, bit
assert 'localStorage.getItem("nx_archery' not in GAMES
assert 'localStorage.setItem("nx_archery' not in GAMES
assert "app.js?v=114" in HTML
print("static contract OK")

def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


client = TestClient(app, follow_redirects=False)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


def auth(uid, name):
    r = client.post("/auth", json={
        "initData": make_init_data({"id": uid, "first_name": name})})
    assert r.status_code == 200, r.text
    return r.json()


# Root redirects into the app instead of a bare 404.
r = client.get("/")
assert r.status_code == 302, r.status_code
assert r.headers["location"].endswith("/webapp/"), r.headers["location"]

# Suggested-users rate limit actually bites (tiny budget patched in).
auth(111, "AudAye")
old = main_mod.RATE_LIMITS["suggested"]
main_mod.RATE_LIMITS["suggested"] = (2, 3600)
try:
    codes = [client.get("/suggested-users",
                        headers=H(111, "AudAye")).status_code
             for _ in range(3)]
finally:
    main_mod.RATE_LIMITS["suggested"] = old
assert codes[:2] == [200, 200] and codes[2] == 429, codes

# Theme-save rate limit actually bites too.
auth(222, "AudBee")
old = main_mod.RATE_LIMITS["theme"]
main_mod.RATE_LIMITS["theme"] = (1, 3600)
try:
    c1 = client.post("/me/theme", json={"picks": {"bg": "sunset"}},
                     headers=H(222, "AudBee")).status_code
    c2 = client.post("/me/theme", json={"picks": {"bg": "marple"}},
                     headers=H(222, "AudBee")).status_code
finally:
    main_mod.RATE_LIMITS["theme"] = old
assert (c1, c2) == (200, 429), (c1, c2)
# ...and the first (allowed) save is really that member's theme.
assert auth(222, "AudBee")["theme"]["bg"] == "sunset"

print("audit-fix behaviour OK")
print("PHASE 97 OK")
