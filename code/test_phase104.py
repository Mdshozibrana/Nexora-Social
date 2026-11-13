"""Phase 104: six more Theme Colours from the owner's fourth batch
of screenshots (Nov 12) — Instagram colour posts by
illustrator.blog_artist, each a nature photo with its printed
hex labels below it: Pink Hibiscus, Blue Hibiscus, Ripe Mango,
Red Rose, Autumn Maple, Avocado. Labels used as printed and
cross-checked by sampling the pills' own fills (band order and
hues match within JPEG tolerance). The picker now offers
33 shades; none duplicates an earlier one.
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
os.environ["DATABASE_URL"] = "sqlite:///./test_phase104.db"
os.environ["ADMIN_IDS"] = "999"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

from app.main import app

JS = open("webapp/app.js", encoding="utf-8").read()
HTML = open("webapp/index.html", encoding="utf-8").read()

NEW = {
    "pink-hibiscus": ("Pink Hibiscus",
                      ["#8B004E", "#E91584", "#FF6BB1", "#FFB6D9",
                       "#FFE4F1", "#6B8E23", "#2D4D1E"]),
    "blue-hibiscus": ("Blue Hibiscus",
                      ["#8B0022", "#E11D48", "#58B0E6", "#8ED4F7",
                       "#D4F0FF", "#4F8F2D", "#1B4D2E"]),
    "ripe-mango": ("Ripe Mango",
                   ["#E30A17", "#F57C00", "#F4A261", "#F7D117",
                    "#A4C639", "#4E8F2D", "#1F4D1F"]),
    "red-rose": ("Red Rose",
                 ["#6B0013", "#A80D22", "#E1223B", "#2E5D2F",
                  "#4F8F3A", "#A7C957", "#D7E7B8"]),
    "autumn-maple": ("Autumn Maple",
                     ["#8B0D0D", "#D71919", "#F04A20", "#F7931E",
                      "#FFD43B", "#8FB326", "#4E3F0C"]),
    "avocado": ("Avocado",
                ["#0E2010", "#253C1B", "#3E5B2E", "#5B7F49",
                 "#83A56D", "#E5EDDE"]),
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
assert "app.js?v=115" in HTML and "style.css?v=115" in HTML
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
auth(112, "ShadeFan2")
r = client.post("/me/theme",
                json={"picks": {"bg": "pink-hibiscus", "card": None,
                                "accent": "avocado"}},
                headers=H(112, "ShadeFan2"))
assert r.status_code == 200, r.text
back = auth(112, "ShadeFan2")["theme"]
assert back == {"bg": "pink-hibiscus", "card": None,
                "accent": "avocado"}, back

print("new shades save OK")
print("PHASE 104 OK")
