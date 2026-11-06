"""Phase 96: Theme Colours belong to ONE account.

Before this phase the theme lived only in one shared localStorage
key ("nx_theme") on the device — on a phone with two Telegram
accounts the second account inherited the first account's theme, so
it looked like one member's change recoloured everyone's app.

Now: users.theme stores each member's picks per account; /auth
returns them; POST /me/theme saves only the caller's row; the client
caches under a per-account key and drops the old shared key.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase96.db"
os.environ["ADMIN_IDS"] = "999"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

from app.main import app

MAIN = open("app/main.py", encoding="utf-8").read()
MODELS = open("app/models.py", encoding="utf-8").read()
JS = open("webapp/app.js", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()

for bit in ('@app.post("/me/theme")', "_theme_picks",
            '"theme": "VARCHAR(256)"', '"theme": _theme_picks(user)',
            "changing yours never"):
    assert bit in MAIN, bit
assert 'theme = Column(String(256)' in MODELS
for bit in ("loadAccountTheme", '"nx_theme_"', "/me/theme",
            'localStorage.removeItem("nx_theme")', "themeKey()"):
    assert bit in JS, bit
assert 'getItem("nx_theme")' in JS  # legacy migration read only
assert "app.js?v=96" in HTML and "style.css?v=96" in HTML
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


client = TestClient(app)


def auth(uid, name):
    r = client.post("/auth", json={"initData": make_init_data({"id": uid, "first_name": name})})
    assert r.status_code == 200, r.text
    return r.json()


def hdr(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


a = auth(111, "ThemeAye")
b = auth(222, "ThemeBee")
assert a["theme"] == {"bg": None, "card": None, "accent": None}, a["theme"]
assert b["theme"] == {"bg": None, "card": None, "accent": None}

# A picks a theme for two zones.
r = client.post("/me/theme",
                json={"picks": {"bg": "navy-mirage", "card": None,
                                "accent": "sunset"}},
                headers=hdr(111, "ThemeAye"))
assert r.status_code == 200 and r.json()["ok"], r.text

# A gets HER theme back at login; B's login is untouched.
a2 = auth(111, "ThemeAye")
assert a2["theme"] == {"bg": "navy-mirage", "card": None,
                       "accent": "sunset"}, a2["theme"]
b2 = auth(222, "ThemeBee")
assert b2["theme"] == {"bg": None, "card": None, "accent": None}, b2["theme"]

# B picking her own theme does not disturb A's.
r = client.post("/me/theme",
                json={"picks": {"bg": None, "card": "forest-mist",
                                "accent": None}},
                headers=hdr(222, "ThemeBee"))
assert r.status_code == 200, r.text
assert auth(222, "ThemeBee")["theme"]["card"] == "forest-mist"
assert auth(111, "ThemeAye")["theme"]["bg"] == "navy-mirage"

# Invalid shade ids are rejected; garbage zones are ignored safely.
r = client.post("/me/theme",
                json={"picks": {"bg": "BAD ID!!"}},
                headers=hdr(111, "ThemeAye"))
assert r.status_code == 422, r.status_code
assert auth(111, "ThemeAye")["theme"]["bg"] == "navy-mirage"

# A resets to default: all-null clears her stored theme, B keeps hers.
r = client.post("/me/theme",
                json={"picks": {"bg": None, "card": None,
                                "accent": None}},
                headers=hdr(111, "ThemeAye"))
assert r.status_code == 200, r.text
assert auth(111, "ThemeAye")["theme"] == {"bg": None, "card": None,
                                          "accent": None}
assert auth(222, "ThemeBee")["theme"]["card"] == "forest-mist"

# Unauthenticated save is refused.
r = client.post("/me/theme", json={"picks": {"bg": "sunset"}})
assert r.status_code in (401, 403), r.status_code

print("per-account theme behaviour OK")
print("PHASE 96 OK")
