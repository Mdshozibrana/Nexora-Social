"""Phase 98: four more Theme Colours from the owner's third batch
of Pinterest screenshots (Nov 6) — Natural Leaf (sampled from the
leaf board), Teal Ribbon (sampled from the infographic bands),
Modern Palette (printed hex labels), Copper Pay (printed hex
labels on the Rel-Pay brand sheet, cross-checked by sampling).
The picker now offers 27 shades; none duplicates an earlier one.
"""
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase98.db"
os.environ["ADMIN_IDS"] = "999"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

from app.main import app

JS = open("webapp/app.js", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()

NEW = {
    "natural-leaf": ("Natural Leaf",
                     ["#1E4634", "#459566", "#84BB71", "#B19468",
                      "#F5DC9A"]),
    "teal-ribbon": ("Teal Ribbon",
                    ["#155F7A", "#49AEC0", "#FFEFCE", "#EA781E",
                     "#131723"]),
    "modern-palette": ("Modern Palette",
                       ["#051A2D", "#A60E35", "#FEA24F", "#10BBC3",
                        "#068187"]),
    "copper-pay": ("Copper Pay",
                   ["#100F0F", "#653615", "#B66120", "#FFFFFF"]),
}
for pid, (name, stops) in NEW.items():
    assert f'id: "{pid}"' in JS, pid
    assert f'name: "{name}"' in JS, name
    for hx in stops:
        assert hx in JS, (pid, hx)
# exactly 33 palettes, all ids unique
ids = re.findall(r'\{ id: "([a-z0-9-]+)", name: ', JS)
assert len(ids) == 33, len(ids)
assert len(set(ids)) == 33
# the new ids are valid theme saves (Phase 96 id rule)
import re as _re2
for pid in NEW:
    assert _re2.match(r"^[a-z0-9][a-z0-9-]{0,39}$", pid)
assert "app.js?v=110" in HTML and "style.css?v=110" in HTML
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
    r = client.post("/auth", json={
        "initData": make_init_data({"id": uid, "first_name": name})})
    assert r.status_code == 200, r.text
    return r.json()


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


# A member can really save one of the new shades on their account
# and gets it back at login (Phase 96 storage).
auth(111, "ShadeFan")
r = client.post("/me/theme",
                json={"picks": {"bg": "natural-leaf", "card": None,
                                "accent": "copper-pay"}},
                headers=H(111, "ShadeFan"))
assert r.status_code == 200, r.text
back = auth(111, "ShadeFan")["theme"]
assert back == {"bg": "natural-leaf", "card": None,
                "accent": "copper-pay"}, back

print("new shades save OK")
print("PHASE 98 OK")
